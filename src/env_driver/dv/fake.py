"""Deterministic DV contribution used only by public unit tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..core.types import ReadinessResult, SideEffect, StepResult, ValidationReport
from .types import DvActionDefinition, DvPhase


@dataclass
class FakeDvProvider:
    provider_id: str = "fake_dv"
    results: Mapping[str, StepResult] = field(default_factory=dict)
    readiness: ReadinessResult = ReadinessResult(True, "fake DV ready")

    def validate(self, request):
        return ValidationReport.success()

    def actions(self, phase):
        definitions = {
            DvPhase.SERIAL_PREPARE: DvActionDefinition(
                "configure_network",
                "配置异构计算机网络",
                phase,
                SideEffect.IDEMPOTENT,
                600,
                "fake network configuration evidence",
                "fake network configuration failure",
                "do not replay an unknown serial operation",
            ),
            DvPhase.SSH_OPERATE: DvActionDefinition(
                "interactive_operation",
                "执行异构计算机交互操作",
                phase,
                SideEffect.EXTERNAL_UNKNOWN,
                3600,
                "fake interactive completion evidence",
                "fake interactive failure evidence",
                "close the channel and do not replay unknown input",
            ),
        }
        return (definitions[phase],)

    async def execute_power_action(self, action, context):
        return self.results.get(action.value, StepResult.success(f"fake power {action.value}"))

    async def probe_ssh(self, endpoint, context):
        return self.results.get(
            f"probe_{endpoint.value}", StepResult.success(f"fake {endpoint.value} SSH ready")
        )

    async def execute_action(self, action_id, context):
        return self.results.get(action_id, StepResult.success(f"fake action {action_id}"))

    async def verify_ready(self, context):
        return self.readiness
