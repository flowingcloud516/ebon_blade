"""Environment-agnostic asynchronous plan execution."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from .context import ControlContext
from .errors import StepCancelledError, StepStateUnknownError
from .model import EnvironmentModel
from .plan import Phase, Plan
from .steps import Step
from .types import (
    ActionState,
    EnvironmentResult,
    EnvironmentStatus,
    FailurePolicy,
    PhaseResult,
    ReadinessResult,
    SideEffect,
    StepRecord,
    StepResult,
    StepStatus,
)


_OK = {StepStatus.SUCCEEDED, StepStatus.SKIPPED}


class PlanExecutor:
    """Runs a fixed Plan and makes every reached step outcome explicit."""

    async def execute(
        self,
        model: EnvironmentModel,
        plan: Plan,
        context: ControlContext,
    ) -> EnvironmentResult:
        phase_results: list[PhaseResult] = []
        stop = False
        any_started = False
        deadline = (
            asyncio.get_running_loop().time() + plan.timeout
            if plan.timeout is not None
            else None
        )

        for phase in plan.phases:
            records: list[StepRecord] = []
            if stop:
                records.extend(self._blocked_records(phase, "not run because the plan stopped"))
                phase_results.append(
                    PhaseResult(phase.phase_id, phase.title, StepStatus.BLOCKED, tuple(records))
                )
                continue

            for index, step in enumerate(phase.steps):
                if context.cancel_event.is_set():
                    result = StepResult(StepStatus.CANCELLED, "cancelled before step started")
                elif deadline is not None and self._remaining(deadline) <= 0:
                    result = StepResult(
                        StepStatus.FAILED,
                        "plan timed out before step started",
                        error_type="TimeoutError",
                    )
                else:
                    any_started = True
                    result = await self._run_step(step, context, deadline=deadline)
                context.record_step_result(step.step_id, result)
                records.append(StepRecord(step.step_id, step.title, result))

                if result.status not in _OK:
                    can_continue = (
                        step.failure_policy is FailurePolicy.CONTINUE
                        or phase.failure_policy is FailurePolicy.CONTINUE
                    )
                    if not can_continue or result.status in {
                        StepStatus.CANCELLED,
                        StepStatus.UNKNOWN,
                    }:
                        stop = True
                        records.extend(
                            self._blocked_records(
                                phase,
                                f"not run after {step.step_id} ended as {result.status.value}",
                                start=index + 1,
                            )
                        )
                        break

            phase_status = self._phase_status(records)
            phase_results.append(
                PhaseResult(phase.phase_id, phase.title, phase_status, tuple(records))
            )

        terminal_status = self._environment_status(phase_results)
        if terminal_status is not EnvironmentStatus.SUCCEEDED:
            await self._collect_failure_context(model, context, terminal_status)
            return EnvironmentResult(
                context.environment_id,
                terminal_status,
                False,
                f"initialization ended as {terminal_status.value}",
                self._action_state(phase_results, any_started),
                tuple(phase_results),
            )

        try:
            readiness = await model.verify_ready(context)
            if not isinstance(readiness, ReadinessResult):
                raise TypeError("verify_ready() must return ReadinessResult")
        except asyncio.CancelledError:
            readiness = ReadinessResult(False, "final readiness verification was cancelled")
            terminal_status = EnvironmentStatus.CANCELLED
        except BaseException as exc:
            readiness = ReadinessResult(
                False,
                f"final readiness verification failed: {exc}",
                {"error_type": type(exc).__name__},
            )
            terminal_status = EnvironmentStatus.FAILED
        else:
            terminal_status = (
                EnvironmentStatus.SUCCEEDED if readiness.ready else EnvironmentStatus.FAILED
            )

        if terminal_status is not EnvironmentStatus.SUCCEEDED:
            await self._collect_failure_context(model, context, readiness)
        return EnvironmentResult(
            context.environment_id,
            terminal_status,
            readiness.ready,
            readiness.summary,
            ActionState.COMPLETED,
            tuple(phase_results),
            readiness,
        )

    async def _run_step(
        self,
        step: Step,
        context: ControlContext,
        *,
        deadline: float | None,
    ) -> StepResult:
        policy = step.retry_policy
        for attempt in range(1, policy.max_attempts + 1):
            if attempt > 1:
                delay = policy.delay_before(attempt)
                if deadline is not None and delay >= self._remaining(deadline):
                    return StepResult(
                        StepStatus.FAILED,
                        "plan timed out before retry started",
                        error_type="TimeoutError",
                        attempts=attempt - 1,
                    )
                if await self._sleep_or_cancel(delay, context.cancel_event):
                    return StepResult(
                        StepStatus.CANCELLED,
                        "cancelled before retry started",
                        attempts=attempt - 1,
                    )
            timeout = step.timeout
            if deadline is not None:
                remaining = self._remaining(deadline)
                if remaining <= 0:
                    return StepResult(
                        StepStatus.FAILED,
                        "plan timed out before step attempt started",
                        error_type="TimeoutError",
                        attempts=max(1, attempt - 1),
                    )
                timeout = remaining if timeout is None else min(timeout, remaining)
            result = await self._run_once(step, context, timeout=timeout)
            result = replace(result, attempts=attempt)
            if result.status in _OK:
                return result
            retry_safe = step.side_effect in {SideEffect.READ_ONLY, SideEffect.IDEMPOTENT}
            if result.status is StepStatus.UNKNOWN or not retry_safe:
                return result
            if attempt == policy.max_attempts:
                return result
        raise AssertionError("retry loop must return")

    async def _run_once(
        self,
        step: Step,
        context: ControlContext,
        *,
        timeout: float | None,
    ) -> StepResult:
        try:
            operation = step.execute(context)
            result = (
                await asyncio.wait_for(operation, timeout)
                if timeout is not None
                else await operation
            )
            if not isinstance(result, StepResult):
                raise TypeError("step execute() must return StepResult")
            return result
        except (StepCancelledError, asyncio.CancelledError):
            status = (
                StepStatus.CANCELLED
                if step.side_effect is SideEffect.READ_ONLY
                else StepStatus.UNKNOWN
            )
            return StepResult(status, "step was cancelled")
        except asyncio.TimeoutError:
            status = (
                StepStatus.FAILED
                if step.side_effect is SideEffect.READ_ONLY
                else StepStatus.UNKNOWN
            )
            return StepResult(status, "step timed out", error_type="TimeoutError")
        except StepStateUnknownError as exc:
            return StepResult(StepStatus.UNKNOWN, str(exc), error_type=type(exc).__name__)
        except BaseException as exc:
            status = (
                StepStatus.FAILED
                if step.side_effect is SideEffect.READ_ONLY
                else StepStatus.UNKNOWN
            )
            return StepResult(status, str(exc) or type(exc).__name__, error_type=type(exc).__name__)

    @staticmethod
    def _blocked_records(phase: Phase, summary: str, start: int = 0) -> list[StepRecord]:
        return [
            StepRecord(
                step.step_id,
                step.title,
                StepResult(StepStatus.BLOCKED, summary),
            )
            for step in phase.steps[start:]
        ]

    @staticmethod
    def _phase_status(records: list[StepRecord]) -> StepStatus:
        statuses = {record.result.status for record in records}
        for status in (
            StepStatus.UNKNOWN,
            StepStatus.CANCELLED,
            StepStatus.FAILED,
            StepStatus.BLOCKED,
        ):
            if status in statuses:
                return status
        return StepStatus.SUCCEEDED

    @staticmethod
    def _environment_status(phases: list[PhaseResult]) -> EnvironmentStatus:
        statuses = {phase.status for phase in phases}
        if StepStatus.UNKNOWN in statuses:
            return EnvironmentStatus.UNKNOWN
        if StepStatus.CANCELLED in statuses:
            return EnvironmentStatus.CANCELLED
        if StepStatus.FAILED in statuses:
            return EnvironmentStatus.FAILED
        if StepStatus.BLOCKED in statuses:
            return EnvironmentStatus.BLOCKED
        return EnvironmentStatus.SUCCEEDED

    @staticmethod
    def _action_state(
        phases: list[PhaseResult],
        any_started: bool,
    ) -> ActionState:
        if any(
            record.result.status is StepStatus.UNKNOWN
            for phase in phases
            for record in phase.steps
        ):
            return ActionState.UNKNOWN
        return ActionState.COMPLETED if any_started else ActionState.NOT_STARTED

    @staticmethod
    def _remaining(deadline: float) -> float:
        return deadline - asyncio.get_running_loop().time()

    @staticmethod
    async def _sleep_or_cancel(delay: float, cancel_event: asyncio.Event) -> bool:
        if cancel_event.is_set():
            return True
        if delay <= 0:
            return False
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return False
        return True

    @staticmethod
    async def _collect_failure_context(
        model: EnvironmentModel,
        context: ControlContext,
        failure,
    ) -> None:
        try:
            await model.collect_failure_context(context, failure)
        except BaseException:
            pass
