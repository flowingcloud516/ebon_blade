from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
import zipfile

from basic_connector.ssh_connector.models import TransferResult
from env_model import (
    ActionState,
    EffectiveEnvironmentConfig,
    EnvironmentRegistry,
    EnvironmentStatus,
    ReadinessResult,
    StepResult,
    StepStatus,
)
from env_model.context import ControlContext
from env_model.evb import (
    ArtifactPreparationCoordinator,
    EvbModel,
    EvbProviderRegistry,
    EvbRuntimeServices,
    FakeEvbAdapter,
    FileZillaRootManager,
    RequiredParallelCollectorGroup,
    SimpleVersionStore,
)
from env_model.service import EnvironmentControlService


def _zip(path: Path, member: str = "payload.txt") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, b"test payload")


class FakeVersionRemote:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, Path]] = []

    async def list_directories(self, remote_path: str) -> tuple[str, ...]:
        return ("v2", "v1", "v1")

    async def download_tree(self, remote_path: str, local_path: Path) -> None:
        self.downloads.append((remote_path, local_path))
        local_path.mkdir(parents=True)
        _zip(local_path / "firmware.zip", "firmware/image.bin")
        _zip(local_path / "boot-script.zip", "main.py")
        _zip(local_path / "driver.zip")
        _zip(local_path / "third-party.zip")


class FakeCollector:
    required = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1
        if self.fail:
            raise RuntimeError("collector unavailable")

    async def stop(self) -> None:
        self.stopped += 1


class FakeSSH:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.uploads: list[tuple[Path, str, bool, bool]] = []
        self.closed = 0

    async def connect(self) -> None:
        self.connect_calls += 1

    async def upload(self, source, destination, *, atomic, overwrite):
        source = Path(source)
        self.uploads.append((source, destination, atomic, overwrite))
        return TransferResult(str(source), destination, source.stat().st_size, True)

    async def close(self) -> None:
        self.closed += 1


class FakeControlConnector:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


def _config(workspace: Path, filezilla: Path, *, provider_id: str = "fake_evb"):
    connections = {
        f"serial-{letter}": {
            "type": "serial",
            "role": f"serial_{letter}",
            "host": "127.0.0.1",
            "port": 7000 + index,
        }
        for index, letter in enumerate("abcde")
    }
    connections["evb-ssh"] = {
        "type": "ssh",
        "role": "evb_ssh",
        "host": "192.0.2.1",
        "username": "test",
        "password": "not-used-by-fake",
    }
    return EffectiveEnvironmentConfig.from_mapping(
        {
            "environment": {"id": "evb-01", "type": "evb", "name": "EVB 01"},
            "target": {"platform": "platform-a", "version": "v1"},
            "evb": {"provider_id": provider_id},
            "local": {"filezilla_root": str(filezilla)},
            "connections": connections,
        }
    )


class ProviderContractTests(unittest.TestCase):
    def test_provider_registration_is_explicit_and_missing_provider_fails(self):
        registry = EvbProviderRegistry()
        with self.assertRaisesRegex(KeyError, "not registered"):
            registry.resolve("private_evb")

        registry.register("fake_evb", FakeEvbAdapter)
        self.assertEqual(registry.provider_ids, ("fake_evb",))
        self.assertEqual(registry.resolve("fake_evb").provider_id, "fake_evb")
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("fake_evb", FakeEvbAdapter)


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_serial_collectors_start_in_parallel(self):
        active = 0
        maximum = 0

        class Probe:
            async def start(self):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1

            async def stop(self):
                return None

        group = RequiredParallelCollectorGroup(Probe() for _ in range(5))
        await group.start()
        await group.stop()
        self.assertEqual(maximum, 5)


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_platform_version_is_downloaded_once_per_run(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            remote = FakeVersionRemote()
            store = SimpleVersionStore(workspace, "/versions", remote)
            coordinator = ArtifactPreparationCoordinator(store)

            first, second = await asyncio.gather(
                coordinator.prepare("platform-a", "v1"),
                coordinator.prepare("platform-a", "v1"),
            )

            self.assertEqual(len(remote.downloads), 1)
            self.assertEqual(first.path, second.path)
            self.assertEqual({first.reused_in_run, second.reused_in_run}, {False, True})
            self.assertTrue((first.path / "firmware.zip").is_file())

    async def test_existing_cache_does_not_contact_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cached = workspace / "versions" / "platform-a" / "v1"
            cached.mkdir(parents=True)
            remote = FakeVersionRemote()
            path = await SimpleVersionStore(workspace, "/versions", remote).ensure_local(
                "platform-a", "v1"
            )
            self.assertEqual(path, cached)
            self.assertEqual(remote.downloads, [])

    async def test_invalid_cache_components_never_escape_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = ArtifactPreparationCoordinator(
                SimpleVersionStore(Path(directory), "/versions", FakeVersionRemote())
            )
            with self.assertRaises(ValueError):
                await coordinator.prepare("../outside", "v1")


class FileZillaSafetyTests(unittest.TestCase):
    def test_adopt_clear_and_extract_preserve_cache_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            served = root / "filezilla"
            workspace.mkdir()
            archive_path = workspace / "versions" / "firmware.zip"
            _zip(archive_path, "firmware/image.bin")
            manager = FileZillaRootManager(workspace, served)
            manager.adopt()
            (served / "old.bin").write_bytes(b"old")
            lease = manager.acquire()
            try:
                manager.clear(lease)
                manager.extract_firmware(archive_path, lease)
            finally:
                lease.release()

            self.assertTrue(archive_path.is_file())
            self.assertTrue((served / ".ebon-filezilla-root").is_file())
            self.assertTrue((served / "firmware" / "image.bin").is_file())
            self.assertFalse((served / "old.bin").exists())

    def test_workspace_or_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            with self.assertRaises(ValueError):
                FileZillaRootManager(workspace, workspace / "served").adopt()

            served = Path(directory) / "served"
            manager = FileZillaRootManager(workspace, served)
            manager.adopt()
            malicious = Path(directory) / "bad.zip"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../escaped.txt", b"bad")
            lease = manager.acquire()
            try:
                with self.assertRaises(ValueError):
                    manager.extract_firmware(malicious, lease)
            finally:
                lease.release()
            self.assertFalse((Path(directory) / "escaped.txt").exists())


class EvbModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.workspace = root / "workspace"
        self.filezilla = root / "filezilla"
        self.workspace.mkdir()
        FileZillaRootManager(self.workspace, self.filezilla).adopt()
        self.remote = FakeVersionRemote()
        self.providers = EvbProviderRegistry()
        self.providers.register("fake_evb", FakeEvbAdapter)
        self.collectors: list[FakeCollector] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _services(self, collector_factory=None) -> EvbRuntimeServices:
        if collector_factory is None:
            def collector_factory(_host, _port, _path):
                collector = FakeCollector()
                self.collectors.append(collector)
                return collector
        return EvbRuntimeServices(
            self.workspace,
            ArtifactPreparationCoordinator(
                SimpleVersionStore(self.workspace, "/versions", self.remote)
            ),
            self.providers,
            serial_collector_factory=collector_factory,
        )

    def test_core_owns_the_fixed_four_phase_plan(self):
        model = EvbModel(self._services())
        config = _config(self.workspace, self.filezilla)
        context = ControlContext(config, {})

        plan = model.build_initialize_plan(context)

        self.assertEqual(tuple(phase.phase_id for phase in plan.phases),
                         ("material", "configure", "start", "operate"))
        self.assertEqual(plan.phases[0].steps[0].step_id, "0.1.artifacts.resolve")
        self.assertIn("1.3.filezilla.clear_root",
                      tuple(step.step_id for step in plan.phases[1].steps))
        self.assertEqual(plan.phases[3].steps[0].step_id, "3.1.evb_ssh.wait_ready")
        self.assertIn("provider.start.start_environment",
                      tuple(step.step_id for step in plan.phases[2].steps))

    async def test_full_fake_run_starts_logs_before_control_and_uses_ssh_after_start(self):
        services = self._services()
        model = EvbModel(services)
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(
            registry,
            run_directory=self.workspace / "runs" / "run-1",
        )
        ssh = FakeSSH()
        connector_calls: list[str] = []

        def connector_factory(connection):
            connector_calls.append(connection.connection_id)
            return ssh if connection.connector_type == "ssh" else FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla),
            connector_factory=connector_factory,
        )
        await service.finish_run()

        self.assertEqual(result.status, EnvironmentStatus.SUCCEEDED)
        self.assertTrue(result.ready)
        self.assertEqual(result.action_state, ActionState.COMPLETED)
        self.assertEqual(tuple(phase.phase_id for phase in result.phases),
                         ("material", "configure", "start", "operate"))
        self.assertEqual(len(self.collectors), 5)
        self.assertTrue(all(item.started == 1 and item.stopped == 1 for item in self.collectors))
        self.assertEqual(ssh.connect_calls, 1)
        self.assertTrue(model._state.log_activation.evb_ssh_ready.is_set())
        self.assertEqual([item[1] for item in ssh.uploads],
                         ["/tmp/driver.zip", "/tmp/third-party.zip"])
        self.assertEqual(len(connector_calls), 6)

    async def test_start_failure_prevents_ssh_and_upload(self):
        failing = FakeEvbAdapter(
            results={
                "start_environment": StepResult(StepStatus.FAILED, "startup rejected")
            }
        )
        self.providers = EvbProviderRegistry()
        self.providers.register("fake_evb", lambda: failing)
        model = EvbModel(self._services())
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        ssh = FakeSSH()

        def connector_factory(connection):
            return ssh if connection.connector_type == "ssh" else FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla),
            connector_factory=connector_factory,
        )
        await service.finish_run()
        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertEqual(ssh.connect_calls, 0)
        self.assertEqual(ssh.uploads, [])
        self.assertFalse(model._state.log_activation.evb_ssh_ready.is_set())
        self.assertTrue(model._state.filezilla_lease.released)

    async def test_unknown_start_state_keeps_filezilla_lease_for_manual_disposition(self):
        class UnknownStartProvider(FakeEvbAdapter):
            async def execute_action(self, action_id, context):
                if action_id == "start_environment":
                    raise RuntimeError("connection lost after startup was dispatched")
                return await super().execute_action(action_id, context)

        provider = UnknownStartProvider()
        self.providers = EvbProviderRegistry()
        self.providers.register("fake_evb", lambda: provider)
        model = EvbModel(self._services())
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        ssh = FakeSSH()

        def connector_factory(connection):
            return ssh if connection.connector_type == "ssh" else FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla),
            connector_factory=connector_factory,
        )
        await service.finish_run()

        self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
        self.assertEqual(ssh.connect_calls, 0)
        self.assertFalse(model._state.filezilla_lease.released)
        model._state.filezilla_lease.release()

    async def test_required_serial_log_failure_blocks_before_connectors(self):
        def collector_factory(_host, _port, _path):
            return FakeCollector(fail=True)

        model = EvbModel(self._services(collector_factory))
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        connector_calls = 0

        def connector_factory(_connection):
            nonlocal connector_calls
            connector_calls += 1
            return FakeControlConnector()

        config = _config(self.workspace, self.filezilla)
        first = await service.initialize(config, connector_factory=connector_factory)
        second = await service.initialize(config, connector_factory=connector_factory)
        await service.finish_run()

        self.assertEqual(first.status, EnvironmentStatus.FAILED)
        self.assertEqual(first.action_state, ActionState.NOT_STARTED)
        self.assertIn("collector failed", first.summary)
        self.assertEqual(second.status, EnvironmentStatus.FAILED)
        self.assertEqual(connector_calls, 0)

    async def test_unregistered_provider_is_an_explicit_preflight_failure(self):
        model = EvbModel(self._services())
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        connector_calls = 0

        def connector_factory(_connection):
            nonlocal connector_calls
            connector_calls += 1
            return FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla, provider_id="private_evb"),
            connector_factory=connector_factory,
        )

        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertEqual(result.action_state, ActionState.NOT_STARTED)
        self.assertIn("not registered", result.summary)
        self.assertEqual(connector_calls, 0)

    async def test_missing_artifact_blocks_all_provider_and_ssh_actions(self):
        class MissingArtifactRemote(FakeVersionRemote):
            async def download_tree(self, remote_path, local_path):
                await super().download_tree(remote_path, local_path)
                (local_path / "third-party.zip").unlink()

        class RecordingProvider(FakeEvbAdapter):
            calls: list[str]

            def __init__(self):
                super().__init__()
                self.calls = []

            async def execute_action(self, action_id, context):
                self.calls.append(action_id)
                return await super().execute_action(action_id, context)

        provider = RecordingProvider()
        self.remote = MissingArtifactRemote()
        self.providers = EvbProviderRegistry()
        self.providers.register("fake_evb", lambda: provider)
        model = EvbModel(self._services())
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        ssh = FakeSSH()

        def connector_factory(connection):
            return ssh if connection.connector_type == "ssh" else FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla),
            connector_factory=connector_factory,
        )
        await service.finish_run()

        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertEqual(provider.calls, [])
        self.assertEqual(ssh.connect_calls, 0)

    async def test_final_readiness_failure_never_reports_ready(self):
        provider = FakeEvbAdapter(
            readiness=ReadinessResult(False, "final read-only probe failed")
        )
        self.providers = EvbProviderRegistry()
        self.providers.register("fake_evb", lambda: provider)
        model = EvbModel(self._services())
        registry = EnvironmentRegistry()
        registry.register("evb", lambda: model)
        service = EnvironmentControlService(registry, run_directory=self.workspace / "run")
        ssh = FakeSSH()

        def connector_factory(connection):
            return ssh if connection.connector_type == "ssh" else FakeControlConnector()

        result = await service.initialize(
            _config(self.workspace, self.filezilla),
            connector_factory=connector_factory,
        )
        await service.finish_run()

        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertFalse(result.ready)
        self.assertEqual(result.summary, "final read-only probe failed")
        self.assertTrue(all(phase.status is StepStatus.SUCCEEDED for phase in result.phases))


if __name__ == "__main__":
    unittest.main()
