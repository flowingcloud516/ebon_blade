"""Public EVB EnvironmentModel assembled from common steps and a trusted plugin."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..context import ControlContext
from ..logs import LogCollector, LogContext
from ..model import EnvironmentModel
from ..plan import Phase, Plan
from ..types import (
    ConnectionRequirement,
    Dependency,
    EffectiveEnvironmentConfig,
    EnvironmentDefinition,
    ReadinessResult,
    StepStatus,
    ValidationIssue,
    ValidationReport,
)
from .adapter import (
    EvbActionContext,
    EvbProviderRegistry,
    EvbExecutionState,
    EvbLogActivation,
    EvbPhase,
    EvbRunRequest,
)
from .artifacts import ArtifactPreparationCoordinator
from .collectors import RequiredParallelCollectorGroup, SharedSerialLogCollector
from .filezilla import EvbWorkspaceMaterializer
from .steps import (
    AcquireFileZillaLeaseStep,
    ProviderActionStep,
    ClearFileZillaRootStep,
    CompleteStartupStep,
    EnsureArtifactsStep,
    ExtractBootScriptStep,
    ExtractFirmwareStep,
    PrepareWorkspaceArtifactsStep,
    ReleaseFileZillaLeaseStep,
    RequireBundleStep,
    ResolveArtifactsStep,
    UploadPackageStep,
    ValidateFileZillaRootStep,
    WaitForEvbSshStep,
)


SERIAL_ROLES = tuple(f"serial_{letter}" for letter in "abcde")


SerialCollectorFactory = Callable[[str, int, Path], LogCollector]


@dataclass(frozen=True)
class EvbRuntimeServices:
    workspace_root: Path
    artifacts: ArtifactPreparationCoordinator
    providers: EvbProviderRegistry
    materializer: EvbWorkspaceMaterializer | None = None
    serial_collector_factory: SerialCollectorFactory = SharedSerialLogCollector

    def __post_init__(self) -> None:
        root = self.workspace_root.resolve()
        object.__setattr__(self, "workspace_root", root)
        if self.materializer is None:
            object.__setattr__(self, "materializer", EvbWorkspaceMaterializer(root))

    @property
    def adapters(self) -> EvbProviderRegistry:
        """Compatibility view for callers using the initial adapter terminology."""
        return self.providers


class EvbModel(EnvironmentModel):
    def __init__(self, services: EvbRuntimeServices) -> None:
        self.services = services
        self._state: EvbExecutionState | None = None
        self._provider = None
        self._log_activation: EvbLogActivation | None = None

    @classmethod
    def definition(cls) -> EnvironmentDefinition:
        requirements = [
            ConnectionRequirement(role, "serial") for role in SERIAL_ROLES
        ]
        requirements.append(ConnectionRequirement("evb_ssh", "ssh"))
        return EnvironmentDefinition(
            "evb",
            "EVB",
            connection_requirements=tuple(requirements),
            capabilities=frozenset({"artifact_prepare", "firmware_start", "ssh_deploy"}),
        )

    def validate_config(self, config: EffectiveEnvironmentConfig) -> ValidationReport:
        issues: list[ValidationIssue] = []
        try:
            request = self._request(config)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.failure("evb_config_invalid", str(exc), "evb")

        try:
            provider = self.services.providers.resolve(request.provider_id)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.failure("evb_provider_unavailable", str(exc), "evb.provider_id")

        try:
            plugin_report = provider.validate(request)
        except Exception as exc:
            plugin_report = None
            issues.append(
                ValidationIssue(
                    "evb_provider_validation_failed",
                    f"EVB provider validation raised {type(exc).__name__}",
                    "evb.provider_id",
                )
            )
        if plugin_report is not None and not isinstance(plugin_report, ValidationReport):
            issues.append(
                ValidationIssue(
                    "evb_provider_validation_invalid",
                    "EVB provider validate() must return ValidationReport",
                    "evb.provider_id",
                )
            )
        elif plugin_report is not None:
            issues.extend(plugin_report.issues)

        try:
            provider.artifact_layout(request)
            provider.workspace_layout(request).resolved(request.workspace_root)
            provider.deployment_layout(request)
            actions = []
            for phase in EvbPhase:
                declared = provider.actions(phase)
                if not isinstance(declared, tuple):
                    raise TypeError("EVB provider actions() must return a tuple")
                for action in declared:
                    if not hasattr(action, "action_id") or not hasattr(action, "phase"):
                        raise TypeError("EVB provider returned an invalid action definition")
                    if action.phase is not phase:
                        raise ValueError(
                            f"action {action.action_id!r} was returned for the wrong phase"
                        )
                    actions.append(action)
            ids = [action.action_id for action in actions]
            if len(ids) != len(set(ids)):
                raise ValueError("EVB provider action IDs must be unique across phases")
            for phase in EvbPhase:
                if not any(action.phase is phase for action in actions):
                    raise ValueError(f"EVB provider must declare at least one {phase.value} action")
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    "evb_provider_definition_invalid",
                    str(exc) or type(exc).__name__,
                    "evb.provider_id",
                )
            )

        return ValidationReport(tuple(issues))

    def dependencies(self, config: EffectiveEnvironmentConfig) -> tuple[Dependency, ...]:
        return ()

    def create_log_collectors(self, context: LogContext) -> tuple[LogCollector, ...]:
        request = self._request(context.config)
        directory = context.directory
        if directory is None:
            raise ValueError("EVB logging requires a run directory")
        serial_collectors: list[LogCollector] = []
        for role in SERIAL_ROLES:
            connection = self._connection_for_role(context.config, role)
            try:
                host = str(connection.parameters["host"])
                port = int(connection.parameters["port"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{role} needs host and port") from exc
            serial_collectors.append(
                self.services.serial_collector_factory(
                    host,
                    port,
                    directory / f"{role}.raw.log",
                )
            )
        collectors: list[LogCollector] = [RequiredParallelCollectorGroup(serial_collectors)]
        provider = self.services.providers.resolve(request.provider_id)
        activation = EvbLogActivation()
        self._log_activation = activation
        collectors.extend(provider.create_log_collectors(request, context, activation))
        return tuple(collectors)

    def build_initialize_plan(self, context: ControlContext) -> Plan:
        request = self._request(context.config)
        provider = self.services.providers.resolve(request.provider_id)
        activation = self._log_activation or EvbLogActivation()
        state = EvbExecutionState(request, activation)
        self._state = state
        self._provider = provider

        configure_provider_steps = tuple(
            ProviderActionStep(item, state, provider)
            for item in provider.actions(EvbPhase.CONFIGURE)
        )
        start_provider_steps = tuple(
            ProviderActionStep(item, state, provider)
            for item in provider.actions(EvbPhase.START)
        )
        operate_provider_steps = tuple(
            ProviderActionStep(item, state, provider)
            for item in provider.actions(EvbPhase.OPERATE)
        )
        deployment = provider.deployment_layout(request)

        material = Phase(
            "material",
            "备料",
            (
                ResolveArtifactsStep(state),
                EnsureArtifactsStep(state, self.services.artifacts, provider),
                RequireBundleStep(state),
            ),
        )
        configure = Phase(
            "configure",
            "配置",
            (
                AcquireFileZillaLeaseStep(state),
                ValidateFileZillaRootStep(state),
                ClearFileZillaRootStep(state),
                ExtractFirmwareStep(state),
                PrepareWorkspaceArtifactsStep(
                    state,
                    self.services.materializer,
                    provider,
                ),
                ExtractBootScriptStep(state, self.services.materializer),
                *configure_provider_steps,
            ),
        )
        start = Phase(
            "start",
            "启动",
            (
                *start_provider_steps,
                CompleteStartupStep(state, start_provider_steps),
                ReleaseFileZillaLeaseStep(state),
            ),
        )
        operate = Phase(
            "operate",
            "环境上操作",
            (
                WaitForEvbSshStep(state),
                UploadPackageStep(
                    "3.3.packages.upload_driver",
                    "上传驱动包",
                    "driver",
                    deployment.driver_remote_path,
                    state,
                ),
                UploadPackageStep(
                    "3.4.packages.upload_third_party",
                    "上传三方包",
                    "third_party",
                    deployment.third_party_remote_path,
                    state,
                ),
                *operate_provider_steps,
            ),
        )
        return Plan("evb.initialize.v1", "1", (material, configure, start, operate))

    async def verify_ready(self, context: ControlContext) -> ReadinessResult:
        state, provider = self._active()
        result = await asyncio.wait_for(
            provider.verify_ready(
                EvbActionContext(
                    state.request,
                    state.bundle,
                    context,
                    state.workspace_layout,
                )
            ),
            timeout=600,
        )
        if not isinstance(result, ReadinessResult):
            raise TypeError("EVB provider verify_ready() must return ReadinessResult")
        return result

    async def collect_failure_context(self, context: ControlContext, failure: Any) -> None:
        if self._state is None:
            return
        lease = self._state.filezilla_lease
        if lease is None or lease.released:
            return
        start_results = (
            result
            for step_id, result in context.step_results.items()
            if step_id.startswith("provider.start.")
        )
        start_state_unknown = any(
            result.status is StepStatus.UNKNOWN for result in start_results
        )
        # Keep the lease only when a reached startup action might still be running.
        if (
            not self._state.start_action_started
            or self._state.start_phase_completed
            or not start_state_unknown
        ):
            lease.release()
        # An UNKNOWN startup action deliberately keeps the cross-process lease file.

    def _active(self):
        if self._state is None or self._provider is None or self._state.bundle is None:
            raise RuntimeError("EVB initialization state is unavailable")
        return self._state, self._provider

    def _request(self, config: EffectiveEnvironmentConfig) -> EvbRunRequest:
        raw = config.raw
        target = self._mapping(raw, "target")
        evb = self._mapping(raw, "evb")
        local = self._mapping(raw, "local")
        platform = self._text(target, "platform")
        version = self._text(target, "version")
        adapter_id = self._text(evb, "provider_id", fallback="adapter_id")
        filezilla_root = Path(self._text(local, "filezilla_root"))
        ssh = self._connection_for_role(config, "evb_ssh")
        return EvbRunRequest(
            config.environment_id,
            platform,
            version,
            adapter_id,
            self.services.workspace_root,
            filezilla_root,
            ssh.connection_id,
            raw,
        )

    @staticmethod
    def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        item = value.get(key)
        if not isinstance(item, Mapping):
            raise ValueError(f"EVB config needs a {key!r} mapping")
        return item

    @staticmethod
    def _text(value: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
        item = value.get(key)
        if item is None and fallback is not None:
            item = value.get(fallback)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"EVB config needs non-empty {key!r}")
        return item.strip()

    @staticmethod
    def _connection_for_role(config: EffectiveEnvironmentConfig, role: str):
        matches = [
            item for item in config.connections.values()
            if item.enabled and item.role == role
        ]
        if len(matches) != 1:
            raise ValueError(f"EVB config needs exactly one enabled {role!r} connection")
        return matches[0]
