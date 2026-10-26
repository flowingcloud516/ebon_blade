"""Immutable initialization plan structure."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import DefinitionError
from .steps import Step
from .types import FailurePolicy


_PLAN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _PLAN_ID.fullmatch(value):
        raise DefinitionError(f"invalid {name}: {value!r}")


@dataclass(frozen=True)
class Phase:
    phase_id: str
    title: str
    steps: tuple[Step, ...]
    failure_policy: FailurePolicy = FailurePolicy.STOP_PLAN

    def __post_init__(self) -> None:
        _identifier(self.phase_id, "phase_id")
        if not isinstance(self.title, str) or not self.title.strip():
            raise DefinitionError("phase title must not be empty")
        if not isinstance(self.failure_policy, FailurePolicy):
            raise DefinitionError("phase failure_policy must be a FailurePolicy")
        if not self.steps:
            raise DefinitionError("a phase must contain at least one step")
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise DefinitionError(f"phase {self.phase_id!r} has duplicate step IDs")


@dataclass(frozen=True)
class Plan:
    plan_id: str
    version: str
    phases: tuple[Phase, ...]
    timeout: float | None = None

    def __post_init__(self) -> None:
        _identifier(self.plan_id, "plan_id")
        if not isinstance(self.version, str) or not self.version.strip():
            raise DefinitionError("plan version must not be empty")
        if not self.phases:
            raise DefinitionError("a plan must contain at least one phase")
        if self.timeout is not None and self.timeout <= 0:
            raise DefinitionError("plan timeout must be positive")
        phase_ids = [phase.phase_id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise DefinitionError("plan phase IDs must be unique")
        step_ids = [step.step_id for phase in self.phases for step in phase.steps]
        if len(step_ids) != len(set(step_ids)):
            raise DefinitionError("step IDs must be unique across a plan")
