"""Opt-in tests for the internal network. Nothing runs without EBON_SSH_* vars."""
import asyncio
import os
from pathlib import Path
import shlex
import shlex
from tempfile import TemporaryDirectory
import unittest

from basic_connector.ssh_connector import (
    CommandRequest, CompletionPolicy, HostKeyPolicy, HostKeySettings,
    ManagedSSHSession, Matcher, SSHConfig,
)


HOST = os.environ.get("EBON_SSH_HOST")
USER = os.environ.get("EBON_SSH_USER")
PASSWORD = os.environ.get("EBON_SSH_PASSWORD")
PORT = int(os.environ.get("EBON_SSH_PORT", "22"))
ENABLED = bool(HOST and USER and PASSWORD)
REMOTE_TMP = os.environ.get("EBON_SSH_REMOTE_TMP")
B_HOST = os.environ.get("EBON_SSH_B_HOST")
B_USER = os.environ.get("EBON_SSH_B_USER")
B_PASSWORD = os.environ.get("EBON_SSH_B_PASSWORD")
REMOTE_TMP = os.environ.get("EBON_SSH_REMOTE_TMP")
B_HOST = os.environ.get("EBON_SSH_B_HOST")
B_USER = os.environ.get("EBON_SSH_B_USER")
B_PASSWORD = os.environ.get("EBON_SSH_B_PASSWORD")


@unittest.skipUnless(ENABLED, "set EBON_SSH_HOST, EBON_SSH_USER and EBON_SSH_PASSWORD")
class InternalSSHTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        host_keys = HostKeySettings(
            environment_id=os.environ.get("EBON_SSH_ENV_ID", "internal-test"),
            store_path=Path(self.temp.name) / "host_keys.json",
            policy=HostKeyPolicy.ENVIRONMENT_PINNED,
        )
        self.session = ManagedSSHSession(SSHConfig(
            host=HOST, port=PORT, username=USER, password=PASSWORD,
            host_keys=host_keys,
        ))
        await self.session.connect()

    async def asyncTearDown(self):
        await self.session.close()
        self.temp.cleanup()

    async def test_01_basic_command(self):
        result = await self.session.run(CommandRequest("printf 'EBON_SSH_OK\\n'"))
        self.assertTrue(result.succeeded)
        self.assertIn("EBON_SSH_OK", result.stdout_tail)

    async def test_02_expect_and_long_connection_reuse(self):
        for index in range(3):
            result = await self.session.run(CommandRequest(
                f"printf 'READY_{index}\\n'",
                completion=CompletionPolicy.EXIT_OR_EXPECT,
                expected=(Matcher(f"READY_{index}", "ready"),),
            ))
            self.assertTrue(result.succeeded)
            self.assertEqual(result.matched, "ready")

    async def test_03_stdout_and_stderr(self):
        result = await self.session.run(CommandRequest(
            "printf 'out\\n'; printf 'err\\n' >&2"
        ))
        self.assertTrue(result.succeeded)
        self.assertIn("out", result.stdout_tail)
        self.assertIn("err", result.stderr_tail)

    @unittest.skipUnless(REMOTE_TMP, "set EBON_SSH_REMOTE_TMP to an allowed remote test directory")
    async def test_04_sftp_roundtrip(self):
        local = Path(self.temp.name) / "upload.txt"
        downloaded = Path(self.temp.name) / "download.txt"
        local.write_text("ebon-blade-sftp-test\n", encoding="utf-8")
        remote = REMOTE_TMP.rstrip("/") + "/ebon-blade-sftp-test.txt"
        uploaded = await self.session.upload(local, remote)
        self.assertTrue(uploaded.verified)
        received = await self.session.download(remote, downloaded)
        self.assertTrue(received.verified)
        self.assertEqual(downloaded.read_bytes(), local.read_bytes())
        await self.session.run(CommandRequest("rm -f -- " + shlex.quote(remote)))

    @unittest.skipUnless(B_HOST and B_USER and B_PASSWORD,
                         "set EBON_SSH_B_HOST, EBON_SSH_B_USER and EBON_SSH_B_PASSWORD")
    async def test_05_jump_to_b(self):
        b_keys = HostKeySettings(
            environment_id=os.environ.get("EBON_SSH_B_ENV_ID", "internal-test-b"),
            store_path=Path(self.temp.name) / "host_keys.json",
            policy=HostKeyPolicy.ENVIRONMENT_PINNED,
        )
        child = await self.session.open_jump(SSHConfig(
            host=B_HOST, username=B_USER, password=B_PASSWORD,
            port=int(os.environ.get("EBON_SSH_B_PORT", "22")), host_keys=b_keys,
        ))
        result = await child.run(CommandRequest("printf 'EBON_SSH_B_OK\\n'"))
        self.assertTrue(result.succeeded)
        self.assertIn("EBON_SSH_B_OK", result.stdout_tail)

    @unittest.skipUnless(REMOTE_TMP, "set EBON_SSH_REMOTE_TMP to an allowed remote test directory")
    async def test_04_sftp_roundtrip(self):
        local = Path(self.temp.name) / "upload.txt"
        downloaded = Path(self.temp.name) / "download.txt"
        local.write_text("ebon-blade-sftp-test\n", encoding="utf-8")
        remote = REMOTE_TMP.rstrip("/") + "/ebon-blade-sftp-test.txt"
        uploaded = await self.session.upload(local, remote)
        self.assertTrue(uploaded.verified)
        received = await self.session.download(remote, downloaded)
        self.assertTrue(received.verified)
        self.assertEqual(downloaded.read_bytes(), local.read_bytes())
        await self.session.run(CommandRequest("rm -f -- " + shlex.quote(remote)))

    @unittest.skipUnless(B_HOST and B_USER and B_PASSWORD,
                         "set EBON_SSH_B_HOST, EBON_SSH_B_USER and EBON_SSH_B_PASSWORD")
    async def test_05_jump_to_b(self):
        b_keys = HostKeySettings(
            environment_id=os.environ.get("EBON_SSH_B_ENV_ID", "internal-test-b"),
            store_path=Path(self.temp.name) / "host_keys.json",
            policy=HostKeyPolicy.ENVIRONMENT_PINNED,
        )
        child = await self.session.open_jump(SSHConfig(
            host=B_HOST, username=B_USER, password=B_PASSWORD,
            port=int(os.environ.get("EBON_SSH_B_PORT", "22")), host_keys=b_keys,
        ))
        result = await child.run(CommandRequest("printf 'EBON_SSH_B_OK\\n'"))
        self.assertTrue(result.succeeded)
        self.assertIn("EBON_SSH_B_OK", result.stdout_tail)


if __name__ == "__main__":
    unittest.main()
