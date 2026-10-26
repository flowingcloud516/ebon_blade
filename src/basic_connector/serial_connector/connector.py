from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
import inspect
import time
from typing import Awaitable, Callable

from .errors import (
    SerialCancelledError, SerialConnectionLostError, SerialIdleTimeoutError,
    SerialMatchFailure, SerialTimeoutError,
)
from .models import (
    CompletionPolicy, Matcher, SerialCommandRequest, SerialConfig, SerialResult,
    SessionMode, SessionState,
)
from .transport import RawTcpBackend, SerialTransport


Observer = Callable[[bytes], None | Awaitable[None]]


class ManagedSerialSession:
    """One task-scoped network serial connection with a single background reader."""

    def __init__(self, config: SerialConfig, backend=None):
        self.config = config
        self._backend = backend or RawTcpBackend()
        self._transport: SerialTransport | None = None
        self._reader_task: asyncio.Task | None = None
        self._command_lock = asyncio.Lock()
        self._condition = asyncio.Condition()
        self._chunks: deque[tuple[int, bytes]] = deque()
        self._start_sequence = 0
        self._next_sequence = 0
        self._buffer_size = 0
        self._last_data_at = time.monotonic()
        self._disconnect_error: BaseException | None = None
        self._observers: set[Observer] = set()
        self._raw_log = None
        self.state = SessionState.DISCONNECTED

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def connect(self) -> None:
        if self.state is SessionState.CLOSED:
            raise SerialConnectionLostError("session is closed")
        if self.state is SessionState.READY:
            return
        self.state = SessionState.CONNECTING
        try:
            self._transport = await self._backend.connect(self.config)
            self._disconnect_error = None
            if self.config.raw_log_path and self._raw_log is None:
                self.config.raw_log_path.parent.mkdir(parents=True, exist_ok=True)
                self._raw_log = self.config.raw_log_path.open("ab")
            self._reader_task = asyncio.create_task(self._reader_loop())
            self.state = SessionState.READY
            if self.config.mode is SessionMode.CONTROL and self.config.probe_expected:
                await self._probe_unlocked()
        except BaseException:
            self.state = SessionState.DISCONNECTED
            await self._close_transport()
            raise

    async def reconnect(self) -> None:
        if self.state is SessionState.CLOSED:
            raise SerialConnectionLostError("session is closed")
        self.state = SessionState.RECONNECTING
        await self._stop_connection()
        last_error: BaseException | None = None
        for delay in (0.0, *self.config.reconnect.delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                self.state = SessionState.DISCONNECTED
                await self.connect()
                return
            except (OSError, asyncio.TimeoutError, SerialConnectionLostError,
                    SerialTimeoutError) as error:
                last_error = error
                self.state = SessionState.RECONNECTING
        self.state = SessionState.DISCONNECTED
        raise SerialConnectionLostError("bounded reconnect attempts exhausted") from last_error

    async def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        self.state = SessionState.CLOSED
        await self._stop_connection()
        if self._raw_log is not None:
            self._raw_log.close()
            self._raw_log = None
        async with self._condition:
            self._condition.notify_all()

    def add_observer(self, observer: Observer) -> Callable[[], None]:
        self._observers.add(observer)
        return lambda: self._observers.discard(observer)

    async def probe(self) -> SerialResult:
        if self.config.mode is SessionMode.OBSERVE_ONLY:
            raise PermissionError("OBSERVE_ONLY session must never write")
        async with self._command_lock:
            await self.connect()
            return await self._probe_unlocked()

    async def _probe_unlocked(self) -> SerialResult:
        request = SerialCommandRequest(
            raw_bytes=self.config.line_ending,
            line_ending=b"",
            expected=self.config.probe_expected,
            total_timeout=self.config.probe_timeout,
        )
        start = self._next_sequence
        try:
            self._transport.write(self.config.line_ending)
            await self._transport.drain()
            self._last_data_at = time.monotonic()
        except (OSError, ConnectionError) as error:
            raise SerialConnectionLostError("connection probe write failed") from error
        return await self._wait_for(
            start, request.expected, (), request.total_timeout, None,
            request.output_tail_limit, None, None,
        )

    async def run(
        self, request: SerialCommandRequest, cancel_event: asyncio.Event | None = None
    ) -> SerialResult:
        if self.config.mode is SessionMode.OBSERVE_ONLY:
            raise PermissionError("OBSERVE_ONLY session must never write")
        async with self._command_lock:
            await self.connect()
            start = self._next_sequence
            payload = request.raw_bytes
            if payload is None:
                payload = request.command.encode(self.config.encoding)
            payload += self.config.line_ending if request.line_ending is None else request.line_ending
            try:
                self._transport.write(payload)
                await self._transport.drain()
                # Idle timeout measures silence after this transaction begins,
                # not how long the task-scoped connection was idle beforehand.
                self._last_data_at = time.monotonic()
            except (OSError, ConnectionError) as error:
                recovered = await self._recover_after_loss()
                raise SerialConnectionLostError(
                    f"write failed; connection recovered={recovered}; command was not replayed"
                ) from error
            if request.completion is CompletionPolicy.WRITE_ONLY:
                return SerialResult(True, "written", None, "")
            matchers = request.expected
            if request.completion is CompletionPolicy.PROMPT_REQUIRED:
                matchers = (request.prompt,)
            try:
                return await self._wait_for(
                    start, matchers, request.failure, request.total_timeout,
                    request.idle_timeout, request.output_tail_limit, cancel_event,
                    request.quiet_period if request.completion is CompletionPolicy.QUIET_AFTER_EXPECT else None,
                )
            except SerialConnectionLostError as error:
                recovered = await self._recover_after_loss()
                raise SerialConnectionLostError(
                    f"connection lost while command state is unknown; recovered={recovered}; command was not replayed"
                ) from error

    async def observe(
        self,
        expected: tuple[Matcher, ...],
        *,
        failure: tuple[Matcher, ...] = (),
        total_timeout: float = 600.0,
        idle_timeout: float | None = None,
        output_tail_limit: int = 64 * 1024,
        cancel_event: asyncio.Event | None = None,
    ) -> SerialResult:
        if not expected:
            raise ValueError("observe needs an expected matcher")
        await self.connect()
        return await self._wait_for(
            self._next_sequence, expected, failure, total_timeout, idle_timeout,
            output_tail_limit, cancel_event, None,
        )

    async def _wait_for(
        self, start: int, expected: tuple[Matcher, ...], failure: tuple[Matcher, ...],
        total_timeout: float, idle_timeout: float | None, tail_limit: int,
        cancel_event: asyncio.Event | None, quiet_period: float | None,
    ) -> SerialResult:
        deadline = time.monotonic() + total_timeout
        matched: Matcher | None = None
        matched_at = 0.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise SerialCancelledError("serial wait cancelled")
            text = self._text_since(start)
            for item in failure:
                if item.matches(text):
                    return SerialResult(False, "failure_match", item.name, text[-tail_limit:])
            if matched is None:
                for item in expected:
                    if item.matches(text):
                        matched = item
                        matched_at = self._last_data_at
                        break
            if matched is not None and quiet_period is None:
                return SerialResult(True, "expect", matched.name, text[-tail_limit:])
            now = time.monotonic()
            if matched is not None and now - max(matched_at, self._last_data_at) >= quiet_period:
                return SerialResult(True, "expect_then_quiet", matched.name, text[-tail_limit:])
            if self._disconnect_error is not None or self.state in {
                SessionState.DISCONNECTED, SessionState.SUSPECT, SessionState.CLOSED
            }:
                raise SerialConnectionLostError("serial stream disconnected") from self._disconnect_error
            if now >= deadline:
                raise SerialTimeoutError("serial wait total timeout")
            if idle_timeout is not None and now - self._last_data_at >= idle_timeout:
                raise SerialIdleTimeoutError("serial output idle timeout")
            wake = min(deadline - now, 0.1)
            if idle_timeout is not None:
                wake = min(wake, max(0.001, idle_timeout - (now - self._last_data_at)))
            if quiet_period is not None and matched is not None:
                wake = min(wake, max(0.001, quiet_period - (now - self._last_data_at)))
            async with self._condition:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), wake)

    async def _reader_loop(self) -> None:
        try:
            while True:
                data = await self._transport.read(self.config.read_size)
                if not data:
                    raise SerialConnectionLostError("serial server closed the connection")
                self._append(data)
                if self._raw_log is not None:
                    self._raw_log.write(data)
                    self._raw_log.flush()
                for observer in tuple(self._observers):
                    try:
                        result = observer(data)
                        if inspect.isawaitable(result):
                            asyncio.create_task(result)
                    except Exception:
                        continue
                async with self._condition:
                    self._condition.notify_all()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._disconnect_error = error
            if self.state is not SessionState.CLOSED:
                self.state = SessionState.SUSPECT
            async with self._condition:
                self._condition.notify_all()

    def _append(self, data: bytes) -> None:
        sequence = self._next_sequence
        self._next_sequence += len(data)
        self._chunks.append((sequence, data))
        self._buffer_size += len(data)
        self._last_data_at = time.monotonic()
        while self._buffer_size > self.config.buffer_limit and self._chunks:
            seq, chunk = self._chunks.popleft()
            self._buffer_size -= len(chunk)
            self._start_sequence = seq + len(chunk)

    def _text_since(self, sequence: int) -> str:
        parts = []
        for chunk_start, chunk in self._chunks:
            chunk_end = chunk_start + len(chunk)
            if chunk_end <= sequence:
                continue
            offset = max(0, sequence - chunk_start)
            parts.append(chunk[offset:])
        return b"".join(parts).decode(self.config.encoding, self.config.decode_errors)

    async def _recover_after_loss(self) -> bool:
        try:
            await self.reconnect()
            return True
        except SerialConnectionLostError:
            return False

    async def _stop_connection(self) -> None:
        task, self._reader_task = self._reader_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._close_transport()

    async def _close_transport(self) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            with suppress(Exception):
                await transport.close()
