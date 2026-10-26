import asyncio
import re
import unittest

from basic_connector.serial_connector import (
    CompletionPolicy, ManagedSerialSession, Matcher, ReconnectPolicy,
    SerialCommandRequest, SerialConfig, SerialConnectionLostError, SessionMode,
)


class FakeTransport:
    def __init__(self):
        self.reads = asyncio.Queue()
        self.writes = []
        self.closed = False

    async def read(self, _size):
        item = await self.reads.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def write(self, data):
        if self.closed:
            raise OSError("closed")
        self.writes.append(data)

    async def drain(self):
        await asyncio.sleep(0)

    async def close(self):
        self.closed = True

    def feed(self, data):
        self.reads.put_nowait(data)


class FakeBackend:
    def __init__(self, transports=None, failures=0):
        self.transports = list(transports or [FakeTransport()])
        self.failures = failures
        self.calls = 0

    async def connect(self, _config):
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError("offline")
        return self.transports.pop(0)


def config(**updates):
    values = dict(host="serial", port=2001,
                  reconnect=ReconnectPolicy(delays=(0, 0)))
    values.update(updates)
    return SerialConfig(**values)


class ModelTests(unittest.TestCase):
    def test_matcher_supports_string_regex_callback(self):
        self.assertTrue(Matcher("ready").matches("ready"))
        self.assertTrue(Matcher(re.compile(r"ok\d")).matches("ok2"))
        self.assertTrue(Matcher(lambda value: value.endswith("done")).matches("done"))

    def test_observe_only_rejects_probe(self):
        with self.assertRaises(ValueError):
            config(mode=SessionMode.OBSERVE_ONLY, probe_expected=(Matcher("#"),))


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_reused_commands_serial_and_old_output_not_matched(self):
        transport = FakeTransport()
        session = ManagedSerialSession(config(), FakeBackend([transport]))
        await session.connect()
        transport.feed(b"OLD READY\n")
        await asyncio.sleep(0)
        first = asyncio.create_task(session.run(SerialCommandRequest("one", expected=(Matcher("ONE"),))))
        await asyncio.sleep(0.01)
        self.assertFalse(first.done())
        transport.feed(b"ONE READY\n")
        self.assertTrue((await first).succeeded)
        second = asyncio.create_task(session.run(SerialCommandRequest("two", expected=(Matcher("TWO"),))))
        await asyncio.sleep(0.01)
        transport.feed(b"TWO READY\n")
        await second
        self.assertEqual(transport.writes, [b"one\r", b"two\r"])
        await session.close()

    async def test_failure_match_and_quiet_after_expect(self):
        transport = FakeTransport()
        session = ManagedSerialSession(config(), FakeBackend([transport]))
        failure = asyncio.create_task(session.run(SerialCommandRequest(
            "bad", expected=(Matcher("OK"),), failure=(Matcher("ERROR", "error"),)
        )))
        await asyncio.sleep(0.01)
        transport.feed(b"ERROR\n")
        self.assertFalse((await failure).succeeded)
        quiet = asyncio.create_task(session.run(SerialCommandRequest(
            "slow", expected=(Matcher("DONE", "done"),),
            completion=CompletionPolicy.QUIET_AFTER_EXPECT, quiet_period=.02,
        )))
        await asyncio.sleep(0.01)
        transport.feed(b"DONE")
        self.assertEqual((await quiet).trigger, "expect_then_quiet")
        await session.close()

    async def test_probe_on_connect_and_observe_only_never_writes(self):
        control_transport = FakeTransport()
        control_transport.feed(b"prompt#")
        control = ManagedSerialSession(config(probe_expected=(Matcher("#"),)),
                                       FakeBackend([control_transport]))
        await control.connect()
        self.assertEqual(control_transport.writes, [b"\r"])
        await control.close()

        observe_transport = FakeTransport()
        observe = ManagedSerialSession(config(mode=SessionMode.OBSERVE_ONLY),
                                       FakeBackend([observe_transport]))
        waiter = asyncio.create_task(observe.observe((Matcher("BOOTED"),), total_timeout=1))
        await asyncio.sleep(0.01)
        observe_transport.feed(b"BOOTED")
        self.assertTrue((await waiter).succeeded)
        self.assertEqual(observe_transport.writes, [])
        with self.assertRaises(PermissionError):
            await observe.run(SerialCommandRequest("x", expected=(Matcher("x"),)))
        await observe.close()

    async def test_observers_share_reader(self):
        transport = FakeTransport()
        session = ManagedSerialSession(config(), FakeBackend([transport]))
        seen_a, seen_b = [], []
        session.add_observer(seen_a.append)
        session.add_observer(seen_b.append)
        await session.connect()
        transport.feed(b"hello")
        await asyncio.sleep(0.01)
        self.assertEqual(seen_a, [b"hello"])
        self.assertEqual(seen_b, [b"hello"])
        await session.close()

    async def test_disconnect_reconnects_but_does_not_replay_command(self):
        first, second = FakeTransport(), FakeTransport()
        backend = FakeBackend([first, second])
        session = ManagedSerialSession(config(), backend)
        task = asyncio.create_task(session.run(SerialCommandRequest(
            "danger", expected=(Matcher("DONE"),), total_timeout=1
        )))
        await asyncio.sleep(0.01)
        first.feed(b"")
        with self.assertRaisesRegex(SerialConnectionLostError, "not replayed"):
            await task
        self.assertEqual(first.writes, [b"danger\r"])
        self.assertEqual(second.writes, [])
        self.assertEqual(backend.calls, 2)
        await session.close()

    async def test_reconnect_with_probe_does_not_deadlock_or_replay(self):
        first, second = FakeTransport(), FakeTransport()
        second.feed(b"prompt#")
        session = ManagedSerialSession(
            config(probe_expected=(Matcher("#"),)), FakeBackend([first, second])
        )
        first.feed(b"prompt#")
        await session.connect()
        task = asyncio.create_task(session.run(SerialCommandRequest(
            "danger", expected=(Matcher("DONE"),), total_timeout=1
        )))
        await asyncio.sleep(0.01)
        first.feed(b"")
        with self.assertRaises(SerialConnectionLostError):
            await asyncio.wait_for(task, 1)
        self.assertEqual(first.writes, [b"\r", b"danger\r"])
        self.assertEqual(second.writes, [b"\r"])
        await session.close()


if __name__ == "__main__":
    unittest.main()
