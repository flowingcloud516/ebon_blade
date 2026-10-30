from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from basic_connector.bmc_connector import IssuePolicy, PowerOperationStatus, PowerState
from env_driver import (
    ConnectionConfig,
    EffectiveEnvironmentConfig,
    EnvironmentControlService,
    EnvironmentRegistry,
    EnvironmentStatus,
    ReadinessResult,
    StepResult,
    StepStatus,
)
from env_driver.dv import (
    DvDriver,
    DvProviderRegistry,
    DvRuntimeServices,
    FakeDvProvider,
)


def dv_config(provider_id="fake_dv"):
    connections = {
        "bmc-main": ConnectionConfig("bmc-main", "bmc", "linux_bmc", True, {"host": "bmc"}),
        "serial-a": ConnectionConfig(
            "serial-a", "serial", "serial_a", True, {"host": "serial", "port": 2001}
        ),
        "serial-b": ConnectionConfig(
            "serial-b", "serial", "serial_b", True, {"host": "serial", "port": 2002}
        ),
        "ssh-linux": ConnectionConfig(
            "ssh-linux", "ssh", "linux_ssh", True, {"host": "linux"}
        ),
        "ssh-accelerator": ConnectionConfig(
            "ssh-accelerator", "ssh", "accelerator_ssh", True, {"host": "accelerator"}
        ),
    }
    return EffectiveEnvironmentConfig(
        "dv-1",
        "dv",
        "DV 1",
        connections,
        {"dv": {"provider_id": provider_id}},
    )


class FakeRequiredCollector:
    required = True

    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    async def start(self):
        self.events.append("collector.start")
        if self.fail:
            raise OSError("collector offline")

    async def stop(self):
        self.events.append("collector.stop")


class FakeBmc:
    def __init__(self, events):
        self.events = events
        self.closed = False

    async def get_power_state(self):
        self.events.append("bmc.get_state")
        return PowerState.ON

    async def force_off(self, *, issue_policy):
        self.events.append(f"bmc.force_off.{issue_policy.value}")
        return self._result(PowerState.OFF)

    async def power_on(self, *, issue_policy):
        self.events.append(f"bmc.power_on.{issue_policy.value}")
        return self._result(PowerState.ON)

    @staticmethod
    def _result(final_state):
        return SimpleNamespace(
            status=PowerOperationStatus.SUCCEEDED,
            diagnostic_summary="power verified",
            changed=True,
            action_issued=True,
            verified=True,
            final_state=final_state,
        )

    async def close(self):
        self.closed = True
        self.events.append("bmc.close")


class FakeSerial:
    def __init__(self, name, events):
        self.name = name
        self.events = events
        self.closed = False

    async def connect(self):
        self.events.append(f"{self.name}.connect")

    async def close(self):
        self.closed = True
        self.events.append(f"{self.name}.close")


class FakeSsh:
    def __init__(self, name, events):
        self.name = name
        self.events = events
        self.closed = False
        self.parent = None

    async def connect(self):
        self.events.append(f"{self.name}.connect")

    async def connect_via(self, parent):
        self.parent = parent
        self.events.append(f"{self.name}.connect_via.{parent.name}")

    async def close(self):
        self.closed = True
        self.events.append(f"{self.name}.close")


class RecordingDvProvider(FakeDvProvider):
    def __init__(self, events, **kwargs):
        super().__init__(**kwargs)
        self.events = events

    async def execute_power_action(self, action, context):
        self.events.append(f"provider.power.{action.value}")
        return await super().execute_power_action(action, context)

    async def probe_ssh(self, endpoint, context):
        self.events.append(f"provider.probe.{endpoint.value}")
        return await super().probe_ssh(endpoint, context)

    async def execute_action(self, action_id, context):
        self.events.append(f"provider.action.{action_id}")
        return await super().execute_action(action_id, context)

    async def verify_ready(self, context):
        self.events.append("provider.verify_ready")
        return await super().verify_ready(context)


class DvDriverTests(unittest.IsolatedAsyncioTestCase):
    def _services(self, provider, events, *, collector_fail=False):
        providers = DvProviderRegistry()
        providers.register(provider.provider_id, lambda: provider)

        def collector_factory(host, port, path):
            self.assertEqual((host, port), ("serial", 2002))
            self.assertEqual(path.name, "serial_b.raw.log")
            return FakeRequiredCollector(events, fail=collector_fail)

        return DvRuntimeServices(providers, collector_factory)

    async def test_fixed_plan_runs_in_strict_order_and_uses_jump_ssh(self):
        events = []
        provider = RecordingDvProvider(events)
        with TemporaryDirectory() as directory:
            driver = DvDriver(self._services(provider, events))
            registry = EnvironmentRegistry()
            registry.register("dv", lambda: driver)
            service = EnvironmentControlService(registry, run_directory=Path(directory))
            connectors = {
                "bmc-main": FakeBmc(events),
                "serial-a": FakeSerial("serial_a", events),
                "serial-b": FakeSerial("serial_b", events),
                "ssh-linux": FakeSsh("linux_ssh", events),
                "ssh-accelerator": FakeSsh("accelerator_ssh", events),
            }
            result = await service.initialize(
                dv_config(), connector_factory=lambda item: connectors[item.connection_id]
            )

            self.assertEqual(result.status, EnvironmentStatus.SUCCEEDED)
            self.assertTrue(result.ready)
            self.assertEqual(
                tuple(phase.phase_id for phase in result.phases),
                ("precheck", "power_cycle", "serial_prepare", "wait_ssh", "ssh_operate"),
            )
            expected = [
                "collector.start",
                "bmc.get_state",
                "serial_a.connect",
                "serial_b.connect",
                "bmc.force_off.always",
                "provider.power.accelerator_force_off",
                "provider.power.accelerator_power_on",
                "bmc.power_on.always",
                "provider.action.configure_network",
                "linux_ssh.connect",
                "provider.probe.linux",
                "accelerator_ssh.connect_via.linux_ssh",
                "provider.probe.accelerator",
                "provider.action.interactive_operation",
                "provider.probe.linux",
                "provider.probe.accelerator",
                "provider.verify_ready",
            ]
            cursor = 0
            for item in expected:
                cursor = events.index(item, cursor) + 1
            self.assertIs(connectors["ssh-accelerator"].parent, connectors["ssh-linux"])
            self.assertTrue(all(connector.closed for connector in connectors.values()))
            self.assertNotIn("collector.stop", events)
            await service.finish_run()
            self.assertEqual(events[-1], "collector.stop")

    async def test_required_serial_log_failure_blocks_before_connector_creation(self):
        events = []
        provider = RecordingDvProvider(events)
        with TemporaryDirectory() as directory:
            driver = DvDriver(self._services(provider, events, collector_fail=True))
            registry = EnvironmentRegistry()
            registry.register("dv", lambda: driver)
            service = EnvironmentControlService(registry, run_directory=Path(directory))
            connector_calls = 0

            def connector_factory(_item):
                nonlocal connector_calls
                connector_calls += 1
                return FakeSerial("unused", events)

            result = await service.initialize(
                dv_config(), connector_factory=connector_factory
            )
            self.assertEqual(result.status, EnvironmentStatus.FAILED)
            self.assertIn("required environment log collector", result.summary)
            self.assertEqual(connector_calls, 0)
            self.assertEqual(events, ["collector.start", "collector.stop"])
            await service.finish_run()

    async def test_unknown_power_action_blocks_remaining_modifying_steps(self):
        events = []
        provider = RecordingDvProvider(
            events,
            results={
                "accelerator_force_off": StepResult(
                    StepStatus.UNKNOWN, "serial power state unknown"
                )
            },
        )
        with TemporaryDirectory() as directory:
            driver = DvDriver(self._services(provider, events))
            registry = EnvironmentRegistry()
            registry.register("dv", lambda: driver)
            service = EnvironmentControlService(registry, run_directory=Path(directory))
            connectors = {
                "bmc-main": FakeBmc(events),
                "serial-a": FakeSerial("serial_a", events),
                "serial-b": FakeSerial("serial_b", events),
                "ssh-linux": FakeSsh("linux_ssh", events),
                "ssh-accelerator": FakeSsh("accelerator_ssh", events),
            }
            result = await service.initialize(
                dv_config(), connector_factory=lambda item: connectors[item.connection_id]
            )
            self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
            self.assertNotIn("provider.power.accelerator_power_on", events)
            self.assertNotIn("provider.action.configure_network", events)
            await service.finish_run()

    async def test_final_provider_readiness_failure_never_reports_ready(self):
        events = []
        provider = RecordingDvProvider(
            events, readiness=ReadinessResult(False, "internal DV probe failed")
        )
        with TemporaryDirectory() as directory:
            driver = DvDriver(self._services(provider, events))
            registry = EnvironmentRegistry()
            registry.register("dv", lambda: driver)
            service = EnvironmentControlService(registry, run_directory=Path(directory))
            connectors = {
                "bmc-main": FakeBmc(events),
                "serial-a": FakeSerial("serial_a", events),
                "serial-b": FakeSerial("serial_b", events),
                "ssh-linux": FakeSsh("linux_ssh", events),
                "ssh-accelerator": FakeSsh("accelerator_ssh", events),
            }
            result = await service.initialize(
                dv_config(), connector_factory=lambda item: connectors[item.connection_id]
            )
            self.assertEqual(result.status, EnvironmentStatus.FAILED)
            self.assertFalse(result.ready)
            self.assertEqual(result.summary, "internal DV probe failed")
            await service.finish_run()

    async def test_unregistered_provider_fails_before_logs_and_connectors(self):
        events = []
        providers = DvProviderRegistry()
        driver = DvDriver(DvRuntimeServices(providers))
        registry = EnvironmentRegistry()
        registry.register("dv", lambda: driver)
        service = EnvironmentControlService(registry)
        calls = 0

        def connector_factory(_item):
            nonlocal calls
            calls += 1
            return FakeSerial("unused", events)

        result = await service.initialize(
            dv_config(provider_id="missing"), connector_factory=connector_factory
        )
        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertIn("not registered", result.summary)
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
