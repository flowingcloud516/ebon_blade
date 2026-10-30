from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
import random
from pathlib import Path
import posixpath
import shutil
import stat
from typing import Any, Protocol

from .errors import (
    CommandCancelledError,
    CommandIdleTimeoutError,
    CommandTimeoutError,
    ConnectionLostError,
    InteractiveProcessExitedError,
)
from .host_keys import HostKeyStore
from .models import (
    CommandRequest,
    CommandResult,
    CompletionPolicy,
    InteractiveMatchResult,
    InteractiveRequest,
    Matcher,
    RemoteProcessState,
    SSHConfig,
    SessionState,
    TransferResult,
)


OutputCallback = Callable[[str, str], None]


class Backend(Protocol):
    async def connect(self, config: SSHConfig, tunnel: Any = None) -> Any: ...
    async def close(self, connection: Any) -> None: ...
    def is_closed(self, connection: Any) -> bool: ...
    async def create_process(self, connection: Any, request: CommandRequest) -> Any: ...
    async def create_interactive_process(
        self, connection: Any, request: InteractiveRequest
    ) -> Any: ...
    async def open_sftp(self, connection: Any) -> Any: ...


class AsyncSSHBackend:
    """Thin adapter which keeps AsyncSSH out of the public connector API."""

    def __init__(self):
        self._host_key_stores: dict[tuple[str, str], HostKeyStore] = {}

    async def connect(self, config: SSHConfig, tunnel: Any = None) -> Any:
        try:
            import asyncssh
        except ImportError as exc:
            raise RuntimeError("AsyncSSH is required; install project dependencies") from exc

        client_factory = None
        known_hosts: Any = ()
        server_host_key_algs: Any = ()
        if config.host_keys:
            store_key = (str(config.host_keys.store_path.resolve()), config.host_keys.environment_id)
            store = self._host_key_stores.setdefault(store_key, HostKeyStore(config.host_keys))

            class ValidatingClient(asyncssh.SSHClient):
                def validate_host_public_key(self, host, addr, port, key):
                    return store.verify(key.get_fingerprint("sha256"))

            client_factory = ValidatingClient
            # An empty set keeps host-key verification active so the custom
            # callback runs. None would disable verification in AsyncSSH.
            known_hosts = b""
            server_host_key_algs = "default"

        return await asyncssh.connect(
            config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            known_hosts=known_hosts,
            client_factory=client_factory,
            server_host_key_algs=server_host_key_algs,
            tunnel=tunnel if tunnel is not None else (),
            connect_timeout=config.connect_timeout,
            login_timeout=config.login_timeout,
            keepalive_interval=config.keepalive_interval,
            keepalive_count_max=config.keepalive_count_max,
        )

    async def close(self, connection: Any) -> None:
        connection.close()
        await connection.wait_closed()

    def is_closed(self, connection: Any) -> bool:
        return connection.is_closed()

    async def create_process(self, connection: Any, request: CommandRequest) -> Any:
        return await connection.create_process(request.command, encoding=request.encoding)

    async def create_interactive_process(
        self, connection: Any, request: InteractiveRequest
    ) -> Any:
        options: dict[str, Any] = {"encoding": request.encoding}
        if request.pty:
            options.update(term_type=request.term_type, term_size=request.term_size)
        return await connection.create_process(request.command, **options)

    async def open_sftp(self, connection: Any) -> Any:
        return await connection.start_sftp_client()


class ManagedSSHSession:
    """Task-scoped SSH connection; each command receives its own channel."""

    def __init__(self, config: SSHConfig, backend: Backend | None = None,
                 tunnel_parent: ManagedSSHSession | None = None):
        self.config = config
        self.backend = backend or AsyncSSHBackend()
        self.state = SessionState.DISCONNECTED
        self._connection: Any = None
        self._connect_lock = asyncio.Lock()
        self._tunnel_parent = tunnel_parent
        self._children: set[ManagedSSHSession] = set()
        self._interactive_sessions: set[InteractiveSSHSession] = set()

    async def __aenter__(self) -> ManagedSSHSession:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.state is SessionState.CLOSED:
                raise ConnectionLostError("SSH session is closed")
            if self._connection is not None and not self.backend.is_closed(self._connection):
                self.state = SessionState.READY
                return
            self.state = SessionState.CONNECTING
            try:
                tunnel = None
                if self._tunnel_parent is not None:
                    await self._tunnel_parent.connect()
                    tunnel = self._tunnel_parent._connection
                self._connection = await self.backend.connect(self.config, tunnel=tunnel)
            except Exception:
                self.state = SessionState.DISCONNECTED
                raise
            self.state = SessionState.READY

    async def reconnect(self) -> None:
        if self.state is SessionState.CLOSED:
            raise ConnectionLostError("SSH session is closed")
        self.state = SessionState.RECONNECTING
        await self._discard_connection()
        last_error: Exception | None = None
        for delay in (0.0, *self.config.reconnect.delays):
            if delay:
                jitter = delay * self.config.reconnect.jitter
                await asyncio.sleep(max(0.0, delay + random.uniform(-jitter, jitter)))
            try:
                await self.connect()
                return
            except Exception as exc:
                last_error = exc
                self.state = SessionState.RECONNECTING
        self.state = SessionState.DISCONNECTED
        raise ConnectionLostError("SSH reconnect budget exhausted") from last_error

    async def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        for child in tuple(self._children):
            await child.close()
        self._children.clear()
        await self._close_interactive_sessions()
        await self._discard_connection()
        self.state = SessionState.CLOSED

    async def _discard_connection(self) -> None:
        await self._close_interactive_sessions()
        for child in tuple(self._children):
            await child._discard_connection()
            if child.state is not SessionState.CLOSED:
                child.state = SessionState.DISCONNECTED
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                await self.backend.close(connection)
            except Exception:
                pass

    async def _close_interactive_sessions(self) -> None:
        sessions = tuple(self._interactive_sessions)
        if sessions:
            await asyncio.gather(
                *(session.close() for session in sessions),
                return_exceptions=True,
            )
        self._interactive_sessions.clear()

    async def open_jump(self, config: SSHConfig) -> ManagedSSHSession:
        """Open a managed B session tunneled over this A session."""
        await self.connect()
        child = ManagedSSHSession(config, backend=self.backend, tunnel_parent=self)
        self._children.add(child)
        await child.connect()
        return child

    async def connect_via(self, parent: ManagedSSHSession) -> None:
        """Bind this configured session to a parent tunnel and connect it."""
        if parent is self:
            raise ValueError("an SSH session cannot tunnel through itself")
        if self.state is SessionState.CLOSED:
            raise ConnectionLostError("SSH session is closed")
        if self._tunnel_parent not in {None, parent}:
            raise RuntimeError("SSH session is already bound to a different tunnel parent")
        if self._connection is not None and not self.backend.is_closed(self._connection):
            if self._tunnel_parent is parent:
                return
            raise RuntimeError("an already-connected SSH session cannot be rebound")
        self._tunnel_parent = parent
        parent._children.add(self)
        await self.connect()

    async def open_interactive(
        self,
        request: InteractiveRequest,
        *,
        output: OutputCallback | None = None,
    ) -> InteractiveSSHSession:
        await self.connect()
        try:
            process = await self.backend.create_interactive_process(
                self._connection, request
            )
        except (OSError, EOFError) as exc:
            self.state = SessionState.SUSPECT
            raise ConnectionLostError(
                "SSH connection was lost while opening an interactive process"
            ) from exc
        session = InteractiveSSHSession(
            process,
            request,
            output=output,
            on_close=self._interactive_sessions.discard,
        )
        self._interactive_sessions.add(session)
        session.start()
        return session

    async def run(
        self,
        request: CommandRequest,
        output: OutputCallback | None = None,
        cancel: Any = None,
    ) -> CommandResult:
        await self.connect()
        try:
            return await asyncio.wait_for(
                self._run_once(request, output or (lambda stream, text: None), cancel),
                timeout=request.total_timeout,
            )
        except TimeoutError as exc:
            raise CommandTimeoutError(f"command exceeded {request.total_timeout:g}s") from exc
        except (OSError, EOFError) as exc:
            self.state = SessionState.SUSPECT
            raise ConnectionLostError("SSH connection was lost during command") from exc

    async def upload(
        self,
        source: Path,
        destination: str,
        *,
        atomic: bool = True,
        overwrite: bool = True,
        progress: Callable[[int, int], None] | None = None,
    ) -> TransferResult:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        await self.connect()
        sftp = await self.backend.open_sftp(self._connection)
        temporary = f"{destination}.ebon-upload" if atomic else destination
        try:
            if not overwrite:
                try:
                    await sftp.stat(destination)
                except (FileNotFoundError, OSError):
                    pass
                else:
                    raise FileExistsError(destination)
            parent = posixpath.dirname(destination)
            if parent:
                await sftp.makedirs(parent, exist_ok=True)

            def on_progress(src, dst, transferred, total):
                if progress:
                    progress(transferred, total)

            await sftp.put(str(source), temporary, progress_handler=on_progress)
            if atomic:
                if overwrite:
                    try:
                        await sftp.remove(destination)
                    except (FileNotFoundError, OSError):
                        pass
                await sftp.rename(temporary, destination)
            attrs = await sftp.stat(destination)
            remote_size = getattr(attrs, "size", None)
            verified = remote_size == source.stat().st_size
            return TransferResult(str(source), destination, source.stat().st_size, verified)
        finally:
            sftp.exit()

    async def download(
        self,
        source: str,
        destination: Path,
        *,
        overwrite: bool = True,
        progress: Callable[[int, int], None] | None = None,
    ) -> TransferResult:
        destination = destination.resolve()
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".ebon-download")
        await self.connect()
        sftp = await self.backend.open_sftp(self._connection)
        try:
            remote = await sftp.stat(source)

            def on_progress(src, dst, transferred, total):
                if progress:
                    progress(transferred, total)

            await sftp.get(source, str(temporary), progress_handler=on_progress)
            temporary.replace(destination)
            remote_size = getattr(remote, "size", None)
            local_size = destination.stat().st_size
            return TransferResult(source, str(destination), local_size, remote_size == local_size)
        finally:
            sftp.exit()

    async def listdir(
        self,
        source: str,
        *,
        directories_only: bool = False,
    ) -> tuple[str, ...]:
        """List one remote directory without exposing the backend SFTP object."""
        await self.connect()
        sftp = await self.backend.open_sftp(self._connection)
        try:
            names = await sftp.listdir(source)
            result: list[str] = []
            for name in names:
                text = str(name)
                if text in {".", ".."} or "/" in text or "\\" in text:
                    continue
                if directories_only:
                    attrs = await sftp.stat(posixpath.join(source, text))
                    permissions = getattr(attrs, "permissions", None)
                    if permissions is None or not stat.S_ISDIR(permissions):
                        continue
                result.append(text)
            return tuple(sorted(result))
        finally:
            sftp.exit()

    async def download_tree(
        self,
        source: str,
        destination: Path,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> TransferResult:
        """Recursively download one directory through a temporary sibling."""
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".ebon-download-tree")
        if temporary.exists():
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            else:
                temporary.unlink()
        await self.connect()
        sftp = await self.backend.open_sftp(self._connection)
        transferred = 0
        try:
            def on_progress(src, dst, current, total):
                nonlocal transferred
                transferred = max(transferred, int(current))
                if progress:
                    progress(int(current), int(total))

            await sftp.get(
                source,
                str(temporary),
                recurse=True,
                progress_handler=on_progress,
            )
            if not temporary.is_dir():
                raise RuntimeError("recursive SFTP download did not create a directory")
            temporary.replace(destination)
            total_bytes = sum(
                item.stat().st_size for item in destination.rglob("*") if item.is_file()
            )
            return TransferResult(source, str(destination), total_bytes or transferred, True)
        except BaseException:
            if temporary.exists():
                if temporary.is_dir() and not temporary.is_symlink():
                    shutil.rmtree(temporary)
                else:
                    temporary.unlink()
            raise
        finally:
            sftp.exit()

    async def _run_once(self, request: CommandRequest, output: OutputCallback, cancel: Any) -> CommandResult:
        process = await self.backend.create_process(self._connection, request)
        stdout_tail = ""
        stderr_tail = ""
        combined = ""
        matched: str | None = None
        failure_match: str | None = None
        last_output = asyncio.get_running_loop().time()
        match_event = asyncio.Event()

        async def pump(reader: Any, stream_name: str) -> None:
            nonlocal stdout_tail, stderr_tail, combined, matched, failure_match, last_output
            async for chunk in reader:
                text = str(chunk)
                last_output = asyncio.get_running_loop().time()
                output(stream_name, text)
                combined = (combined + text)[-request.output_tail_limit:]
                if stream_name == "stdout":
                    stdout_tail = (stdout_tail + text)[-request.output_tail_limit:]
                else:
                    stderr_tail = (stderr_tail + text)[-request.output_tail_limit:]
                for matcher in request.failure:
                    if matcher.matches(combined):
                        failure_match = matcher.name
                        match_event.set()
                        return
                for matcher in request.expected:
                    if matcher.matches(combined):
                        matched = matcher.name
                        match_event.set()
                        if request.completion is not CompletionPolicy.EXIT_REQUIRED:
                            return

        pumps = [asyncio.create_task(pump(process.stdout, "stdout")),
                 asyncio.create_task(pump(process.stderr, "stderr"))]
        wait_task = asyncio.create_task(process.wait())
        match_task = asyncio.create_task(match_event.wait())
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise CommandCancelledError("command was cancelled")
                if request.idle_timeout is not None:
                    idle = asyncio.get_running_loop().time() - last_output
                    if idle >= request.idle_timeout:
                        raise CommandIdleTimeoutError(f"no command output for {request.idle_timeout:g}s")
                done, _ = await asyncio.wait(
                    (wait_task, match_task), timeout=0.1, return_when=asyncio.FIRST_COMPLETED
                )
                if match_task in done:
                    if failure_match:
                        process.close()
                        return CommandResult(False, "failure_match", None, failure_match,
                                             stdout_tail, stderr_tail, RemoteProcessState.UNKNOWN)
                    if request.completion in {CompletionPolicy.EXPECT_REQUIRED, CompletionPolicy.EXIT_OR_EXPECT}:
                        process.close()
                        return CommandResult(True, "expect", None, matched,
                                             stdout_tail, stderr_tail, RemoteProcessState.UNKNOWN)
                    match_task = asyncio.create_task(asyncio.sleep(10**9))
                if wait_task in done:
                    await asyncio.gather(*pumps, return_exceptions=True)
                    exit_status = getattr(process, "exit_status", None)
                    expected_ok = not request.expected or matched is not None
                    succeeded = exit_status == 0 and expected_ok and failure_match is None
                    return CommandResult(succeeded, "exit", exit_status, matched,
                                         stdout_tail, stderr_tail, RemoteProcessState.EXITED)
        finally:
            for task in (*pumps, wait_task, match_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pumps, wait_task, match_task, return_exceptions=True)


class InteractiveSSHSession:
    """One client-driven line-oriented process channel on a managed SSH connection."""

    def __init__(
        self,
        process: Any,
        request: InteractiveRequest,
        *,
        output: OutputCallback | None = None,
        on_close: Callable[["InteractiveSSHSession"], None] | None = None,
    ) -> None:
        self.process = process
        self.request = request
        self._output = output or (lambda _stream, _text: None)
        self._on_close = on_close
        self._condition = asyncio.Condition()
        self._chunks: deque[tuple[int, str]] = deque()
        self._buffer_size = 0
        self._start_sequence = 0
        self._next_sequence = 0
        self._match_cursor = 0
        self._last_output_at = asyncio.get_running_loop().time()
        self._tasks: list[asyncio.Task] = []
        self._process_wait: asyncio.Task | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        if self._tasks or self._closed:
            return
        self._process_wait = asyncio.create_task(self.process.wait())
        self._tasks = [
            asyncio.create_task(self._pump(self.process.stdout, "stdout")),
            asyncio.create_task(self._pump(self.process.stderr, "stderr")),
            asyncio.create_task(self._watch_process()),
        ]

    async def wait_for(
        self,
        expected: tuple[Matcher, ...],
        *,
        failure: tuple[Matcher, ...] = (),
        total_timeout: float = 600.0,
        idle_timeout: float | None = None,
        output_tail_limit: int = 64 * 1024,
        cancel_event: asyncio.Event | None = None,
    ) -> InteractiveMatchResult:
        if not expected:
            raise ValueError("interactive wait_for needs an expected matcher")
        if total_timeout <= 0 or (idle_timeout is not None and idle_timeout <= 0):
            raise ValueError("interactive wait timeouts must be positive")
        self._ensure_open()
        start = self._match_cursor
        started_at = asyncio.get_running_loop().time()
        deadline = started_at + total_timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CommandCancelledError("interactive wait was cancelled")
            text = self._text_since(start)
            for matcher in failure:
                if matcher.matches(text):
                    self._match_cursor = self._next_sequence
                    return InteractiveMatchResult(
                        False, matcher.name, text[-output_tail_limit:]
                    )
            for matcher in expected:
                if matcher.matches(text):
                    self._match_cursor = self._next_sequence
                    return InteractiveMatchResult(
                        True, matcher.name, text[-output_tail_limit:]
                    )
            if self._closed:
                raise ConnectionLostError("interactive SSH session was closed")
            if self._process_wait is not None and self._process_wait.done():
                raise InteractiveProcessExitedError(
                    "interactive process exited before expected output"
                )
            now = asyncio.get_running_loop().time()
            if now >= deadline:
                raise CommandTimeoutError(
                    f"interactive wait exceeded {total_timeout:g}s"
                )
            if idle_timeout is not None:
                last_output = max(started_at, self._last_output_at)
                if now - last_output >= idle_timeout:
                    raise CommandIdleTimeoutError(
                        f"no interactive output for {idle_timeout:g}s"
                    )
            wake = min(deadline - now, 0.1)
            if idle_timeout is not None:
                wake = min(
                    wake,
                    max(0.001, idle_timeout - (now - max(started_at, self._last_output_at))),
                )
            async with self._condition:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), wake)

    async def send_text(self, text: str, *, sensitive: bool = False) -> None:
        del sensitive  # Inputs are never copied into the transcript.
        self._ensure_open()
        writer = self.process.stdin
        try:
            writer.write(text)
            drain = getattr(writer, "drain", None)
            if drain is not None:
                result = drain()
                if isinstance(result, Awaitable):
                    await result
        except (OSError, EOFError, ConnectionError) as exc:
            raise ConnectionLostError("interactive SSH write failed") from exc

    async def send_line(
        self,
        text: str,
        *,
        line_ending: str = "\n",
        sensitive: bool = False,
    ) -> None:
        await self.send_text(text + line_ending, sensitive=sensitive)

    async def send_control(self, key: str) -> None:
        normalized = key.strip().lower()
        if len(normalized) == 1 and "a" <= normalized <= "z":
            value = chr(ord(normalized) - ord("a") + 1)
        else:
            controls = {"enter": "\r", "escape": "\x1b", "tab": "\t"}
            if normalized not in controls:
                raise ValueError(f"unsupported control key: {key!r}")
            value = controls[normalized]
        await self.send_text(value)

    def transcript_tail(self, limit: int = 64 * 1024) -> str:
        if limit <= 0:
            raise ValueError("transcript tail limit must be positive")
        return self._text_since(max(self._start_sequence, self._next_sequence - limit))[-limit:]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(Exception):
            self.process.close()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            if not task.done():
                task.cancel()
        if self._process_wait is not None and not self._process_wait.done():
            self._process_wait.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._process_wait is not None:
            await asyncio.gather(self._process_wait, return_exceptions=True)
        async with self._condition:
            self._condition.notify_all()
        if self._on_close is not None:
            self._on_close(self)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ConnectionLostError("interactive SSH session is closed")

    async def _pump(self, reader: Any, stream_name: str) -> None:
        try:
            async for chunk in reader:
                text = str(chunk)
                self._append(text)
                self._output(stream_name, text)
                async with self._condition:
                    self._condition.notify_all()
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._condition:
                self._condition.notify_all()

    async def _watch_process(self) -> None:
        if self._process_wait is None:
            return
        with suppress(asyncio.CancelledError, Exception):
            await self._process_wait
        async with self._condition:
            self._condition.notify_all()

    def _append(self, text: str) -> None:
        if not text:
            return
        if len(text) > self.request.buffer_limit:
            skipped = len(text) - self.request.buffer_limit
            self._next_sequence += skipped
            text = text[-self.request.buffer_limit:]
            self._chunks.clear()
            self._buffer_size = 0
            self._start_sequence = self._next_sequence
        sequence = self._next_sequence
        self._next_sequence += len(text)
        self._chunks.append((sequence, text))
        self._buffer_size += len(text)
        self._last_output_at = asyncio.get_running_loop().time()
        while self._buffer_size > self.request.buffer_limit and self._chunks:
            seq, chunk = self._chunks.popleft()
            self._buffer_size -= len(chunk)
            self._start_sequence = seq + len(chunk)

    def _text_since(self, sequence: int) -> str:
        parts: list[str] = []
        for chunk_start, chunk in self._chunks:
            chunk_end = chunk_start + len(chunk)
            if chunk_end <= sequence:
                continue
            offset = max(0, sequence - chunk_start)
            parts.append(chunk[offset:])
        return "".join(parts)
