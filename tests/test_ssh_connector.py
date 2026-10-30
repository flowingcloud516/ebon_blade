import asyncio
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
import unittest

from basic_connector.ssh_connector import (
    CommandRequest, CompletionPolicy, HostKeyPolicy, HostKeySettings,
    InteractiveRequest, ManagedSSHSession, Matcher, ReconnectPolicy, SSHConfig, SessionState,
)
from basic_connector.ssh_connector.errors import (
    CommandCancelledError, CommandTimeoutError, HostKeyError,
    InteractiveProcessExitedError,
)
from basic_connector.ssh_connector.host_keys import HostKeyStore


class FakeReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self.chunks.pop(0)


class FakeProcess:
    def __init__(self, stdout=(), stderr=(), exit_status=0, wait_delay=0):
        self.stdout = FakeReader(stdout)
        self.stderr = FakeReader(stderr)
        self.exit_status = exit_status
        self.wait_delay = wait_delay
        self.closed = False

    async def wait(self):
        await asyncio.sleep(self.wait_delay)

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self, processes=(), connect_failures=0, interactive_processes=()):
        self.processes = list(processes)
        self.interactive_processes = list(interactive_processes)
        self.connect_failures = connect_failures
        self.connect_calls = 0
        self.close_calls = 0
        self.tunnels = []

    async def connect(self, config, tunnel=None):
        self.connect_calls += 1
        self.tunnels.append(tunnel)
        if self.connect_calls <= self.connect_failures:
            raise OSError("offline")
        return {"closed": False, "number": self.connect_calls}

    async def close(self, connection):
        connection["closed"] = True
        self.close_calls += 1

    def is_closed(self, connection):
        return connection["closed"]

    async def create_process(self, connection, request):
        return self.processes.pop(0)

    async def create_interactive_process(self, connection, request):
        return self.interactive_processes.pop(0)

    async def open_sftp(self, connection):
        raise AssertionError("SFTP not configured in this fake")


class _Attrs:
    def __init__(self, *, permissions=None):
        self.permissions = permissions


class FakeTreeSFTP:
    def __init__(self):
        self.exited = False
        self.get_calls = []

    async def listdir(self, source):
        return ["v2", "plain.txt", "../unsafe", "v1"]

    async def stat(self, source):
        mode = stat.S_IFDIR if source.endswith(("/v1", "/v2")) else stat.S_IFREG
        return _Attrs(permissions=mode)

    async def get(self, source, destination, *, recurse, progress_handler):
        self.get_calls.append((source, destination, recurse))
        target = Path(destination)
        target.mkdir(parents=True)
        (target / "artifact.bin").write_bytes(b"payload")
        progress_handler(source, destination, 7, 7)

    def exit(self):
        self.exited = True


class FakeTreeBackend(FakeBackend):
    def __init__(self, sftp):
        super().__init__()
        self.sftp = sftp

    async def open_sftp(self, connection):
        return self.sftp


class QueueReader:
    def __init__(self):
        self.items = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.items.get()
        if item is StopAsyncIteration:
            raise StopAsyncIteration
        return item

    def feed(self, text):
        self.items.put_nowait(text)


class FakeWriter:
    def __init__(self):
        self.writes = []

    def write(self, text):
        self.writes.append(text)

    async def drain(self):
        await asyncio.sleep(0)


class FakeInteractiveProcess:
    def __init__(self):
        self.stdout = QueueReader()
        self.stderr = QueueReader()
        self.stdin = FakeWriter()
        self.exited = asyncio.Event()
        self.closed = False

    async def wait(self):
        await self.exited.wait()

    def close(self):
        self.closed = True
        self.exited.set()


def config(**updates):
    values = dict(host="example", username="user", password="secret",
                  reconnect=ReconnectPolicy(delays=(0, 0), jitter=0))
    values.update(updates)
    return SSHConfig(**values)


class ModelTests(unittest.TestCase):
    def test_secret_is_not_in_config_repr(self):
        self.assertNotIn("secret", repr(config()))

    def test_matcher_supports_string_regex_and_callback(self):
        self.assertTrue(Matcher("ready").matches("system ready"))
        self.assertTrue(Matcher(re.compile(r"ready\s+\d+")).matches("ready 42"))
        self.assertTrue(Matcher(lambda text: text.endswith("ok")).matches("all ok"))

    def test_invalid_command_policies_are_rejected(self):
        with self.assertRaises(ValueError):
            CommandRequest("cmd", completion=CompletionPolicy.EXPECT_REQUIRED)
        with self.assertRaises(ValueError):
            CommandRequest("cmd", side_effect=True, retryable=True)


class HostKeyStoreTests(unittest.TestCase):
    def test_first_key_is_pinned_and_mismatch_is_rejected(self):
        with TemporaryDirectory() as directory:
            settings = HostKeySettings("E001", Path(directory) / "keys.json")
            store = HostKeyStore(settings)
            self.assertTrue(store.verify("SHA256:first"))
            self.assertTrue(store.verify("SHA256:first"))
            with self.assertRaises(HostKeyError):
                store.verify("SHA256:other")

    def test_authorized_reprovision_only_replaces_target(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "keys.json"
            HostKeyStore(HostKeySettings("A", path)).verify("SHA256:a")
            HostKeyStore(HostKeySettings("B", path)).verify("SHA256:old")
            rotating = HostKeyStore(HostKeySettings(
                "B", path, HostKeyPolicy.RESET_FOR_REPROVISION, rotation_authorized=True
            ))
            self.assertTrue(rotating.verify("SHA256:new"))
            self.assertTrue(HostKeyStore(HostKeySettings("A", path)).verify("SHA256:a"))
            with self.assertRaises(HostKeyError):
                HostKeyStore(HostKeySettings("B", path)).verify("SHA256:old")
            with self.assertRaises(HostKeyError):
                rotating.verify("SHA256:third")

    def test_strict_policy_requires_a_preprovisioned_key(self):
        with TemporaryDirectory() as directory:
            store = HostKeyStore(HostKeySettings(
                "E001", Path(directory) / "keys.json", HostKeyPolicy.STRICT
            ))
            with self.assertRaises(HostKeyError):
                store.verify("SHA256:first")


class ManagedSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_is_reused_and_each_command_gets_a_process(self):
        backend = FakeBackend([
            FakeProcess(["one\n"]), FakeProcess(["two\n"]),
        ])
        async with ManagedSSHSession(config(), backend) as session:
            first = await session.run(CommandRequest("one"))
            second = await session.run(CommandRequest("two"))
            self.assertTrue(first.succeeded)
            self.assertTrue(second.succeeded)
            self.assertEqual(backend.connect_calls, 1)
            self.assertEqual(session.state, SessionState.READY)
        self.assertEqual(session.state, SessionState.CLOSED)
        self.assertEqual(backend.close_calls, 1)

    async def test_expect_can_finish_before_process_exit(self):
        process = FakeProcess(["booting\n", "READY\n"], wait_delay=60)
        backend = FakeBackend([process])
        session = ManagedSSHSession(config(), backend)
        result = await session.run(CommandRequest(
            "start", completion=CompletionPolicy.EXPECT_REQUIRED,
            expected=(Matcher("READY", "ready"),), total_timeout=1,
        ))
        self.assertTrue(result.succeeded)
        self.assertEqual(result.trigger, "expect")
        self.assertEqual(result.matched, "ready")
        self.assertTrue(process.closed)
        await session.close()

    async def test_failure_match_wins(self):
        backend = FakeBackend([FakeProcess(stderr=["FATAL: failed\n"], wait_delay=60)])
        session = ManagedSSHSession(config(), backend)
        result = await session.run(CommandRequest(
            "start", completion=CompletionPolicy.EXPECT_REQUIRED,
            expected=(Matcher("READY"),), failure=(Matcher("FATAL", "fatal"),),
            total_timeout=1,
        ))
        self.assertFalse(result.succeeded)
        self.assertEqual(result.matched, "fatal")
        await session.close()

    async def test_reconnect_uses_bounded_attempts(self):
        backend = FakeBackend(connect_failures=2)
        session = ManagedSSHSession(config(), backend)
        await session.reconnect()
        self.assertEqual(backend.connect_calls, 3)
        self.assertEqual(session.state, SessionState.READY)
        await session.close()

    async def test_jump_session_is_connected_through_parent(self):
        backend = FakeBackend([FakeProcess(["on-b\n"])])
        parent = ManagedSSHSession(config(host="a"), backend)
        child = await parent.open_jump(config(host="b"))
        result = await child.run(CommandRequest("hostname"))
        self.assertTrue(result.succeeded)
        self.assertIsNone(backend.tunnels[0])
        self.assertIsNotNone(backend.tunnels[1])
        await parent.close()
        self.assertEqual(parent.state, SessionState.CLOSED)
        self.assertEqual(child.state, SessionState.CLOSED)

    async def test_configured_session_can_connect_via_parent(self):
        backend = FakeBackend()
        parent = ManagedSSHSession(config(host="a"), backend)
        child = ManagedSSHSession(config(host="b"), backend)
        await child.connect_via(parent)
        self.assertIsNone(backend.tunnels[0])
        self.assertIsNotNone(backend.tunnels[1])
        await parent.close()
        self.assertEqual(child.state, SessionState.CLOSED)

    async def test_directory_listing_and_recursive_download_hide_sftp_backend(self):
        with TemporaryDirectory() as directory:
            sftp = FakeTreeSFTP()
            session = ManagedSSHSession(config(), FakeTreeBackend(sftp))
            directories = await session.listdir("/versions", directories_only=True)
            destination = Path(directory) / "downloaded"
            transfer = await session.download_tree("/versions/platform/v1", destination)

            self.assertEqual(directories, ("v1", "v2"))
            self.assertTrue((destination / "artifact.bin").is_file())
            self.assertEqual(transfer.bytes_transferred, 7)
            self.assertTrue(transfer.verified)
            self.assertEqual(sftp.get_calls[0][2], True)
            self.assertTrue(sftp.exited)
            await session.close()

    async def test_interactive_session_matches_new_prompts_and_reuses_process(self):
        process = FakeInteractiveProcess()
        backend = FakeBackend(interactive_processes=[process])
        session = ManagedSSHSession(config(), backend)
        interactive = await session.open_interactive(InteractiveRequest("menu"))

        process.stdout.feed("Select option: ")
        first = await interactive.wait_for((Matcher("Select option", "menu"),), total_timeout=1)
        self.assertTrue(first.succeeded)
        await interactive.send_line("2")
        process.stdout.feed("Enter value: ")
        second = await interactive.wait_for((Matcher("Enter value", "value"),), total_timeout=1)
        self.assertEqual(second.matched, "value")
        await interactive.send_line("secret", sensitive=True)

        self.assertEqual(process.stdin.writes, ["2\n", "secret\n"])
        self.assertNotIn("secret", interactive.transcript_tail())
        await session.close()
        self.assertTrue(process.closed)
        self.assertTrue(interactive.closed)

    async def test_interactive_wait_timeout_cancel_and_early_exit(self):
        timeout_process = FakeInteractiveProcess()
        session = ManagedSSHSession(
            config(), FakeBackend(interactive_processes=[timeout_process])
        )
        interactive = await session.open_interactive(InteractiveRequest("menu"))
        with self.assertRaises(CommandTimeoutError):
            await interactive.wait_for((Matcher("never"),), total_timeout=0.01)
        cancel = asyncio.Event()
        cancel.set()
        with self.assertRaises(CommandCancelledError):
            await interactive.wait_for(
                (Matcher("never"),), total_timeout=1, cancel_event=cancel
            )
        await session.close()

        exited_process = FakeInteractiveProcess()
        exited_session = ManagedSSHSession(
            config(), FakeBackend(interactive_processes=[exited_process])
        )
        exited = await exited_session.open_interactive(InteractiveRequest("menu"))
        exited_process.exited.set()
        await asyncio.sleep(0)
        with self.assertRaises(InteractiveProcessExitedError):
            await exited.wait_for((Matcher("never"),), total_timeout=1)
        await exited_session.close()

    async def test_interactive_transcript_retains_tail_of_oversized_chunk(self):
        process = FakeInteractiveProcess()
        session = ManagedSSHSession(
            config(), FakeBackend(interactive_processes=[process])
        )
        interactive = await session.open_interactive(
            InteractiveRequest("menu", buffer_limit=8)
        )
        process.stdout.feed("0123456789abcdef")
        matched = await interactive.wait_for((Matcher("cdef"),), total_timeout=1)

        self.assertTrue(matched.succeeded)
        self.assertEqual(interactive.transcript_tail(), "89abcdef")
        await session.close()


if __name__ == "__main__":
    unittest.main()
