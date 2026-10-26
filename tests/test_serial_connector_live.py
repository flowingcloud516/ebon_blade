"""Opt-in internal tests. Nothing runs without EBON_SERIAL_HOST and PORT."""
import os
import unittest

from basic_connector.serial_connector import (
    ManagedSerialSession, Matcher, SerialCommandRequest, SerialConfig, SessionMode,
)


HOST = os.environ.get("EBON_SERIAL_HOST")
PORT_TEXT = os.environ.get("EBON_SERIAL_PORT")
ENABLED = bool(HOST and PORT_TEXT)


@unittest.skipUnless(ENABLED, "set EBON_SERIAL_HOST and EBON_SERIAL_PORT")
class InternalSerialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        expected = os.environ.get("EBON_SERIAL_PROBE_EXPECT")
        self.session = ManagedSerialSession(SerialConfig(
            host=HOST,
            port=int(PORT_TEXT),
            line_ending=os.environ.get("EBON_SERIAL_LINE_ENDING", "\\r")
                .encode("utf-8").decode("unicode_escape").encode("utf-8"),
            probe_expected=(Matcher(expected, "probe"),) if expected else (),
            probe_timeout=float(os.environ.get("EBON_SERIAL_PROBE_TIMEOUT", "10")),
        ))
        await self.session.connect()

    async def asyncTearDown(self):
        await self.session.close()

    @unittest.skipUnless(os.environ.get("EBON_SERIAL_PROBE_EXPECT"),
                         "set EBON_SERIAL_PROBE_EXPECT")
    async def test_01_control_probe(self):
        result = await self.session.probe()
        self.assertTrue(result.succeeded)

    @unittest.skipUnless(
        os.environ.get("EBON_SERIAL_SAFE_COMMAND") and
        os.environ.get("EBON_SERIAL_SAFE_EXPECT"),
        "set EBON_SERIAL_SAFE_COMMAND and EBON_SERIAL_SAFE_EXPECT",
    )
    async def test_02_safe_command(self):
        result = await self.session.run(SerialCommandRequest(
            command=os.environ["EBON_SERIAL_SAFE_COMMAND"],
            expected=(Matcher(os.environ["EBON_SERIAL_SAFE_EXPECT"], "safe"),),
            total_timeout=float(os.environ.get("EBON_SERIAL_COMMAND_TIMEOUT", "30")),
            idle_timeout=float(os.environ["EBON_SERIAL_IDLE_TIMEOUT"])
                if os.environ.get("EBON_SERIAL_IDLE_TIMEOUT") else None,
        ))
        self.assertTrue(result.succeeded)


@unittest.skipUnless(ENABLED and os.environ.get("EBON_SERIAL_OBSERVE_EXPECT"),
                     "set endpoint vars and EBON_SERIAL_OBSERVE_EXPECT")
class InternalObserveOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_03_observe_only(self):
        session = ManagedSerialSession(SerialConfig(
            host=HOST, port=int(PORT_TEXT), mode=SessionMode.OBSERVE_ONLY,
        ))
        try:
            result = await session.observe(
                (Matcher(os.environ["EBON_SERIAL_OBSERVE_EXPECT"], "observed"),),
                total_timeout=float(os.environ.get("EBON_SERIAL_OBSERVE_TIMEOUT", "60")),
            )
            self.assertTrue(result.succeeded)
        finally:
            await session.close()


if __name__ == "__main__":
    unittest.main()
