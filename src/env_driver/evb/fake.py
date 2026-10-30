"""Deterministic provider used by public unit tests; it never operates a device."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..core.types import ReadinessResult, SideEffect, StepResult, ValidationReport
from .types import (
    EvbActionContext,
    EvbActionDefinition,
    EvbArtifactLayout,
    EvbDeploymentLayout,
    EvbPhase,
)
from .filezilla import WorkspaceArtifactLayout


@dataclass
class FakeEvbProvider:
    provider_id: str = "fake_evb"
    results: Mapping[str, StepResult] = field(default_factory=dict)
    readiness: ReadinessResult = ReadinessResult(True, "fake EVB ready")

    def validate(self, request):
        return ValidationReport.success()

    def artifact_layout(self, request):
        return EvbArtifactLayout(
            "firmware.zip",
            "boot-script.zip",
            "driver.zip",
            "third-party.zip",
        )

    def workspace_layout(self, request):
        return WorkspaceArtifactLayout(
            "evb/boot-script.zip",
            "evb/boot-script",
            "evb/driver.zip",
            "evb/third-party.zip",
        )

    def deployment_layout(self, request):
        return EvbDeploymentLayout("/tmp/driver.zip", "/tmp/third-party.zip")

    def actions(self, phase):
        definitions = {
            EvbPhase.CONFIGURE: EvbActionDefinition(
                "render_config",
                "生成内部启动配置",
                phase,
                SideEffect.IDEMPOTENT,
                30,
                "fake config generated",
                "fake config rejection",
                "safe local cancellation",
            ),
            EvbPhase.START: EvbActionDefinition(
                "start_environment",
                "执行内部EVB启动",
                phase,
                SideEffect.EXTERNAL_UNKNOWN,
                3600,
                "fake current-run startup evidence",
                "fake startup failure evidence",
                "do not force-stop an unknown remote action",
            ),
            EvbPhase.OPERATE: EvbActionDefinition(
                "environment_operation",
                "执行内部环境操作",
                phase,
                SideEffect.EXTERNAL_UNKNOWN,
                3600,
                "fake operation evidence",
                "fake operation failure evidence",
                "do not force-stop an unknown remote action",
            ),
        }
        return (definitions[phase],)

    def create_log_collectors(self, request, context, activation):
        return ()

    async def execute_action(self, action_id: str, context: EvbActionContext):
        return self.results.get(action_id, StepResult.success(f"fake action {action_id}"))

    async def verify_ready(self, context: EvbActionContext):
        return self.readiness
