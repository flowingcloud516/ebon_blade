"""Executable step contracts used by environment initialization plans."""
from __future__ import annotations

from abc import ABC, abstractmethod
import re
from typing import TYPE_CHECKING

from .errors import DefinitionError
from .types import (
    FailurePolicy,
    RetryPolicy,
    SideEffect,
    StateObservation,
    StepResult,
    StepStatus,
)

if TYPE_CHECKING:
    from .context import ControlContext


_STEP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class Step(ABC):
    """Smallest executable unit in a plan.

    Instances describe work only. Runtime state belongs to the executor and its
    result records, which means a Step can safely be reused in plan templates.
    """

    def __init__(
        self,
        step_id: str,
        title: str,
        *,
        timeout: float | None = None,
        side_effect: SideEffect,
        retry_policy: RetryPolicy | None = None,
        failure_policy: FailurePolicy = FailurePolicy.STOP_PLAN,
    ) -> None:
        if not isinstance(step_id, str) or not _STEP_ID.fullmatch(step_id):
            raise DefinitionError(f"invalid step_id: {step_id!r}")
        if not isinstance(title, str) or not title.strip():
            raise DefinitionError("step_id and title must not be empty")
        if timeout is not None and timeout <= 0:
            raise DefinitionError("step timeout must be positive")
        if not isinstance(side_effect, SideEffect):
            raise DefinitionError("side_effect must be a SideEffect")
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise DefinitionError("retry_policy must be a RetryPolicy")
        if not isinstance(failure_policy, FailurePolicy):
            raise DefinitionError("failure_policy must be a FailurePolicy")
        self.step_id = step_id
        self.title = title
        self.timeout = timeout
        self.side_effect = side_effect
        self.retry_policy = retry_policy or RetryPolicy()
        self.failure_policy = failure_policy

    @abstractmethod
    async def execute(self, context: "ControlContext") -> StepResult:
        """Perform the step and return a terminal, evidence-based result."""


class CheckStep(Step, ABC):
    """Read-only status check. Implementations must never repair state."""

    def __init__(self, step_id: str, title: str, **kwargs) -> None:
        supplied = kwargs.pop("side_effect", SideEffect.READ_ONLY)
        if supplied is not SideEffect.READ_ONLY:
            raise DefinitionError("CheckStep must be read_only")
        super().__init__(step_id, title, side_effect=SideEffect.READ_ONLY, **kwargs)

    async def execute(self, context: "ControlContext") -> StepResult:
        return await self.check(context)

    @abstractmethod
    async def check(self, context: "ControlContext") -> StepResult:
        """Observe state without changing it."""


class EnsureStateStep(Step, ABC):
    """Converge state through inspect -> optional apply -> verify."""

    def __init__(self, step_id: str, title: str, **kwargs) -> None:
        supplied = kwargs.pop("side_effect", SideEffect.IDEMPOTENT)
        if supplied is SideEffect.READ_ONLY:
            raise DefinitionError("EnsureStateStep must declare a modifying side effect")
        super().__init__(step_id, title, side_effect=supplied, **kwargs)

    async def execute(self, context: "ControlContext") -> StepResult:
        before = await self.inspect(context)
        if before.satisfied:
            return StepResult(
                StepStatus.SKIPPED,
                before.summary or "target state already satisfied",
                changed=False,
                details=before.details,
            )
        applied = await self.apply(context)
        if applied.status not in {StepStatus.SUCCEEDED, StepStatus.SKIPPED}:
            return applied
        after = await self.verify(context)
        details = {"before": dict(before.details), "after": dict(after.details)}
        if not after.satisfied:
            return StepResult(
                StepStatus.FAILED,
                after.summary or "target state was not reached",
                changed=applied.changed,
                details=details,
            )
        return StepResult(
            StepStatus.SUCCEEDED,
            after.summary or applied.summary,
            changed=applied.changed,
            details=details,
        )

    @abstractmethod
    async def inspect(self, context: "ControlContext") -> StateObservation:
        """Return StateObservation for the target before changing anything."""

    @abstractmethod
    async def apply(self, context: "ControlContext") -> StepResult:
        """Attempt to converge the target state."""

    @abstractmethod
    async def verify(self, context: "ControlContext") -> StateObservation:
        """Independently observe the target after apply."""


class OperationStep(Step, ABC):
    """An explicit action which runs every time the plan reaches this step."""

    def __init__(self, step_id: str, title: str, **kwargs) -> None:
        supplied = kwargs.pop("side_effect", SideEffect.EXTERNAL_UNKNOWN)
        if supplied is SideEffect.READ_ONLY:
            raise DefinitionError("OperationStep must declare a modifying side effect")
        super().__init__(step_id, title, side_effect=supplied, **kwargs)

    async def execute(self, context: "ControlContext") -> StepResult:
        return await self.perform(context)

    @abstractmethod
    async def perform(self, context: "ControlContext") -> StepResult:
        """Perform and verify this invocation's requested action."""
