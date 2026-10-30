import asyncio
from pathlib import Path
import tempfile
import unittest

from env_driver import (
    ActionState,
    CheckStep,
    ConnectionConfig,
    ConnectionRequirement,
    ContextClosedError,
    ControlContext,
    DefinitionError,
    Dependency,
    EffectiveEnvironmentConfig,
    EnsureStateStep,
    EnvironmentControlService,
    EnvironmentDefinition,
    EnvironmentDriver,
    EnvironmentRegistry,
    EnvironmentStatus,
    LogContext,
    OperationStep,
    Phase,
    Plan,
    PlanExecutor,
    ReadinessResult,
    RegistryError,
    SideEffect,
    StateObservation,
    Step,
    StepResult,
    StepStateUnknownError,
    StepStatus,
    ValidationReport,
)


class ScriptedStep(Step):
    def __init__(self, step_id, action, *, side_effect=SideEffect.READ_ONLY, **kwargs):
        super().__init__(step_id, step_id, side_effect=side_effect, **kwargs)
        self.action = action
        self.calls = 0

    async def execute(self, context):
        self.calls += 1
        value = self.action(context)
        if asyncio.iscoroutine(value):
            value = await value
        if isinstance(value, BaseException):
            raise value
        return value


class FakeCollector:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1


class FakeConnector:
    def __init__(self):
        self.closes = 0

    async def close(self):
        self.closes += 1


class FakeDriver(EnvironmentDriver):
    plan = None
    collector = None
    dependency_ids = ()
    readiness = ReadinessResult(True, "ready")
    verify_calls = 0

    @classmethod
    def definition(cls):
        return EnvironmentDefinition(
            "fake",
            "Fake",
            connection_requirements=(ConnectionRequirement("control", "ssh"),),
        )

    def validate_config(self, config):
        return ValidationReport.success()

    def dependencies(self, config):
        return tuple(Dependency(item) for item in self.dependency_ids)

    def create_log_collectors(self, context: LogContext):
        return () if self.collector is None else (self.collector,)

    def build_initialize_plan(self, context):
        return self.plan

    async def verify_ready(self, context):
        type(self).verify_calls += 1
        return self.readiness


class OtherIdDriver(FakeDriver):
    @classmethod
    def definition(cls):
        return EnvironmentDefinition("other", "Other")


def config():
    connection = ConnectionConfig("ssh-main", "ssh", "control", True, {"host": "x"})
    return EffectiveEnvironmentConfig(
        "host-1", "fake", "Host 1", {connection.connection_id: connection}
    )


def empty_config():
    return EffectiveEnvironmentConfig("host-1", "fake", "Host 1")


def one_step_plan(step):
    return Plan("initialize", "1", (Phase("prepare", "Prepare", (step,)),))


class DefinitionTests(unittest.TestCase):
    def test_registry_rejects_duplicate_mismatch_and_unknown(self):
        registry = EnvironmentRegistry()
        registry.register("fake", FakeDriver)
        self.assertEqual(registry.definitions()[0].type_id, "fake")
        self.assertIsInstance(registry.resolve("fake"), FakeDriver)
        with self.assertRaises(RegistryError):
            registry.register("fake", FakeDriver)
        with self.assertRaises(RegistryError):
            EnvironmentRegistry().register("wrong", OtherIdDriver)
        with self.assertRaises(RegistryError):
            registry.resolve("missing")

    def test_registry_accepts_a_task_local_factory(self):
        registry = EnvironmentRegistry()
        registry.register("fake", lambda: FakeDriver())
        self.assertIsInstance(registry.resolve("fake"), FakeDriver)

    def test_plan_phase_and_step_validation(self):
        ok = ScriptedStep("same", lambda _: StepResult.success("ok"))
        with self.assertRaises(DefinitionError):
            Phase("empty", "Empty", ())
        with self.assertRaises(DefinitionError):
            Phase("duplicate", "Duplicate", (ok, ok))
        with self.assertRaises(DefinitionError):
            Plan("empty", "1", ())
        with self.assertRaises(DefinitionError):
            Plan(
                "duplicate",
                "1",
                (Phase("one", "One", (ok,)), Phase("two", "Two", (ok,))),
            )


class EnsureStep(EnsureStateStep):
    def __init__(self, satisfied):
        super().__init__("ensure", "Ensure")
        self.satisfied = satisfied
        self.applies = 0

    async def inspect(self, context):
        return StateObservation(self.satisfied, "already ready")

    async def apply(self, context):
        self.applies += 1
        self.satisfied = True
        return StepResult.success("changed", changed=True)

    async def verify(self, context):
        return StateObservation(self.satisfied, "ready now")


class CountOperation(OperationStep):
    def __init__(self):
        super().__init__("operation", "Operation", side_effect=SideEffect.IDEMPOTENT)
        self.calls = 0

    async def perform(self, context):
        self.calls += 1
        return StepResult.success("done", changed=True)


class StepSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_skips_apply_when_target_is_already_satisfied(self):
        step = EnsureStep(True)
        result = await step.execute(ControlContext(empty_config(), {}))
        self.assertEqual(result.status, StepStatus.SKIPPED)
        self.assertFalse(result.changed)
        self.assertEqual(step.applies, 0)

    async def test_ensure_applies_and_verifies_when_needed(self):
        step = EnsureStep(False)
        result = await step.execute(ControlContext(empty_config(), {}))
        self.assertEqual(result.status, StepStatus.SUCCEEDED)
        self.assertTrue(result.changed)
        self.assertEqual(step.applies, 1)

    async def test_operation_runs_for_every_invocation(self):
        step = CountOperation()
        context = ControlContext(empty_config(), {})
        await step.execute(context)
        await step.execute(context)
        self.assertEqual(step.calls, 2)


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeDriver.verify_calls = 0

    async def test_success_runs_independent_final_verification(self):
        step = ScriptedStep("check", lambda _: StepResult.success("checked"))
        result = await PlanExecutor().execute(
            FakeDriver(), one_step_plan(step), ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.SUCCEEDED)
        self.assertTrue(result.ready)
        self.assertEqual(FakeDriver.verify_calls, 1)

    async def test_read_only_failure_blocks_remainder_and_skips_verify(self):
        first = ScriptedStep("first", lambda _: ValueError("bad check"))
        second = ScriptedStep("second", lambda _: StepResult.success("not reached"))
        plan = Plan("p", "1", (Phase("p1", "P1", (first, second)),))
        result = await PlanExecutor().execute(
            FakeDriver(), plan, ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertEqual(result.phases[0].steps[0].result.status, StepStatus.FAILED)
        self.assertEqual(result.phases[0].steps[1].result.status, StepStatus.BLOCKED)
        self.assertEqual(FakeDriver.verify_calls, 0)

    async def test_side_effect_exception_and_timeout_are_unknown(self):
        exception_step = ScriptedStep(
            "write", lambda _: StepStateUnknownError("possibly written"),
            side_effect=SideEffect.IDEMPOTENT,
        )
        result = await PlanExecutor().execute(
            FakeDriver(), one_step_plan(exception_step), ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
        self.assertEqual(result.action_state, ActionState.UNKNOWN)

        async def slow(_):
            await asyncio.sleep(0.1)
            return StepResult.success("late")

        timeout_step = ScriptedStep(
            "slow", slow, side_effect=SideEffect.DESTRUCTIVE, timeout=0.001
        )
        result = await PlanExecutor().execute(
            FakeDriver(), one_step_plan(timeout_step), ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
        self.assertEqual(result.action_state, ActionState.UNKNOWN)

    async def test_plan_timeout_limits_a_step_without_its_own_timeout(self):
        async def slow(_):
            await asyncio.sleep(0.1)
            return StepResult.success("late")

        step = ScriptedStep("slow", slow, side_effect=SideEffect.DESTRUCTIVE)
        plan = Plan("p", "1", (Phase("p1", "P1", (step,)),), timeout=0.001)
        result = await PlanExecutor().execute(
            FakeDriver(), plan, ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
        self.assertEqual(result.action_state, ActionState.UNKNOWN)
        self.assertEqual(result.phases[0].steps[0].result.error_type, "TimeoutError")

    async def test_cancelling_an_in_flight_modifying_step_is_unknown(self):
        async def cancelled(_):
            raise asyncio.CancelledError

        step = ScriptedStep(
            "write", cancelled, side_effect=SideEffect.DESTRUCTIVE
        )
        result = await PlanExecutor().execute(
            FakeDriver(), one_step_plan(step), ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.UNKNOWN)
        self.assertEqual(result.action_state, ActionState.UNKNOWN)

    async def test_cooperative_cancel_is_terminal_without_running_step(self):
        step = ScriptedStep("check", lambda _: StepResult.success("should not run"))
        context = ControlContext(empty_config(), {})
        context.cancel_event.set()
        result = await PlanExecutor().execute(FakeDriver(), one_step_plan(step), context)
        self.assertEqual(result.status, EnvironmentStatus.CANCELLED)
        self.assertEqual(result.action_state, ActionState.NOT_STARTED)
        self.assertEqual(step.calls, 0)

    async def test_verify_not_ready_turns_successful_steps_into_failed_environment(self):
        FakeDriver.readiness = ReadinessResult(False, "ssh not ready")
        self.addAsyncCleanup(self._restore_readiness)
        step = ScriptedStep("check", lambda _: StepResult.success("checked"))
        result = await PlanExecutor().execute(
            FakeDriver(), one_step_plan(step), ControlContext(empty_config(), {})
        )
        self.assertEqual(result.status, EnvironmentStatus.FAILED)
        self.assertFalse(result.ready)
        self.assertEqual(result.readiness.summary, "ssh not ready")

    async def _restore_readiness(self):
        FakeDriver.readiness = ReadinessResult(True, "ready")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeDriver.dependency_ids = ()
        FakeDriver.collector = None
        FakeDriver.readiness = ReadinessResult(True, "ready")
        FakeDriver.plan = one_step_plan(
            ScriptedStep("check", lambda _: StepResult.success("checked"))
        )
        self.registry = EnvironmentRegistry()
        self.registry.register("fake", FakeDriver)

    async def test_control_context_closes_shared_connector_once(self):
        connector = FakeConnector()
        connection_a = ConnectionConfig("a", "ssh", "control")
        connection_b = ConnectionConfig("b", "ssh", "control")
        context = ControlContext(
            EffectiveEnvironmentConfig(
                "host-1",
                "fake",
                "Host 1",
                {"a": connection_a, "b": connection_b},
            ),
            {"a": connector, "b": connector},
        )
        self.assertEqual(context.config.environment_id, "host-1")
        self.assertIs(context.resolve_connection("a", connector_type="ssh"), connector)
        await context.close()
        await context.close()
        self.assertEqual(connector.closes, 1)
        with self.assertRaises(ContextClosedError):
            context.resolve_connection("a")

    async def test_service_closes_control_scope_but_logs_wait_for_finish_run(self):
        collector = FakeCollector()
        connector = FakeConnector()
        FakeDriver.collector = collector
        service = EnvironmentControlService(self.registry)
        result = await service.initialize(
            config(), connector_factory=lambda _: connector
        )
        self.assertEqual(result.status, EnvironmentStatus.SUCCEEDED)
        self.assertEqual(connector.closes, 1)
        self.assertEqual(collector.starts, 1)
        self.assertEqual(collector.stops, 0)
        self.assertEqual(service.log_manager.active_environment_ids, ("host-1",))
        await service.finish_run()
        self.assertEqual(collector.stops, 1)
        self.assertEqual(service.log_manager.active_environment_ids, ())

    async def test_reinitialization_reuses_existing_log_session(self):
        collector = FakeCollector()
        FakeDriver.collector = collector
        service = EnvironmentControlService(self.registry)

        first = await service.initialize(
            config(), connector_factory=lambda _: FakeConnector()
        )
        second = await service.initialize(
            config(), connector_factory=lambda _: FakeConnector()
        )

        self.assertEqual(first.status, EnvironmentStatus.SUCCEEDED)
        self.assertEqual(second.status, EnvironmentStatus.SUCCEEDED)
        self.assertEqual(collector.starts, 1)
        await service.finish_run()
        self.assertEqual(collector.stops, 1)

    async def test_service_creates_environment_log_and_control_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            service = EnvironmentControlService(
                self.registry, run_directory=run_directory
            )
            result = await service.initialize(
                config(), connector_factory=lambda _: FakeConnector()
            )

            self.assertEqual(result.status, EnvironmentStatus.SUCCEEDED)
            environment_directory = run_directory / "env" / "host-1"
            self.assertTrue((environment_directory / "collectors").is_dir())
            self.assertTrue((environment_directory / "control").is_dir())
            await service.finish_run()

    async def test_unready_dependency_blocks_before_logs_or_connectors(self):
        FakeDriver.dependency_ids = ("other-host",)
        collector = FakeCollector()
        FakeDriver.collector = collector
        calls = 0

        def connector_factory(_):
            nonlocal calls
            calls += 1
            return FakeConnector()

        service = EnvironmentControlService(self.registry)
        result = await service.initialize(config(), connector_factory=connector_factory)
        self.assertEqual(result.status, EnvironmentStatus.BLOCKED)
        self.assertEqual(result.action_state, ActionState.NOT_STARTED)
        self.assertEqual(calls, 0)
        self.assertEqual(collector.starts, 0)


if __name__ == "__main__":
    unittest.main()
