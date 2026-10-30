"""Public DV EnvironmentDriver assembled around an internal contribution."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..core.context import ControlContext
from ..core.driver import EnvironmentDriver
from ..core.logs import LogCollector, LogContext
from ..core.plan import Plan
from ..core.types import (
    ConnectionRequirement,
    Dependency,
    EffectiveEnvironmentConfig,
    EnvironmentDefinition,
    ReadinessResult,
    StepStatus,
    ValidationIssue,
    ValidationReport,
)
from .collectors import DvSerialLogCollector
from .contract import DvContributionProvider, DvProviderRegistry
from .plan import build_dv_initialize_plan
from .types import (
    DvActionContext,
    DvExecutionState,
    DvPhase,
    DvRunRequest,
    DvSshEndpoint,
)


SerialCollectorFactory = Callable[[str, int, Path], LogCollector]


@dataclass(frozen=True)
class DvRuntimeServices:
    providers: DvProviderRegistry
    serial_collector_factory: SerialCollectorFactory = DvSerialLogCollector


class DvDriver(EnvironmentDriver):
    def __init__(self, services: DvRuntimeServices) -> None:
        self.services = services
        self._state: DvExecutionState | None = None
        self._provider: DvContributionProvider | None = None

    @classmethod
    def definition(cls) -> EnvironmentDefinition:
        return EnvironmentDefinition(
            "dv",
            "DV",
            connection_requirements=(
                ConnectionRequirement("linux_bmc", "bmc"),
                ConnectionRequirement("serial_a", "serial"),
                ConnectionRequirement("serial_b", "serial"),
                ConnectionRequirement("linux_ssh", "ssh"),
                ConnectionRequirement("accelerator_ssh", "ssh"),
            ),
            capabilities=frozenset(
                {"strict_power_cycle", "serial_network_prepare", "jump_ssh", "interactive_ssh"}
            ),
        )

    def validate_config(self, config: EffectiveEnvironmentConfig) -> ValidationReport:
        issues: list[ValidationIssue] = []
        try:
            request = self._request(config)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.failure("dv_config_invalid", str(exc), "dv")
        try:
            provider = self.services.providers.resolve(request.provider_id)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.failure(
                "dv_provider_unavailable", str(exc), "dv.provider_id"
            )

        try:
            report = provider.validate(request)
            if not isinstance(report, ValidationReport):
                raise TypeError("DV provider validate() must return ValidationReport")
            issues.extend(report.issues)
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    "dv_provider_validation_failed",
                    f"DV provider validation raised {type(exc).__name__}",
                    "dv.provider_id",
                )
            )

        try:
            actions = []
            for phase in DvPhase:
                declared = provider.actions(phase)
                if not isinstance(declared, tuple) or not declared:
                    raise TypeError(
                        f"DV provider must return a non-empty tuple for {phase.value}"
                    )
                for action in declared:
                    if action.phase is not phase:
                        raise ValueError(
                            f"action {action.action_id!r} was returned for the wrong phase"
                        )
                    actions.append(action)
            ids = [action.action_id for action in actions]
            if len(ids) != len(set(ids)):
                raise ValueError("DV provider action IDs must be unique across phases")
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    "dv_provider_definition_invalid",
                    str(exc) or type(exc).__name__,
                    "dv.provider_id",
                )
            )

        serial_b = config.connections[request.serial_b_connection_id]
        try:
            host = serial_b.parameters["host"]
            port = int(serial_b.parameters["port"])
            if not isinstance(host, str) or not host.strip() or not 1 <= port <= 65535:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    "dv_serial_b_invalid",
                    "serial_b needs a valid host and port for required logging",
                    "connections",
                )
            )
        return ValidationReport(tuple(issues))

    def dependencies(self, config: EffectiveEnvironmentConfig) -> tuple[Dependency, ...]:
        return ()

    def create_log_collectors(self, context: LogContext) -> tuple[LogCollector, ...]:
        request = self._request(context.config)
        if context.directory is None:
            raise ValueError("DV logging requires a run directory")
        serial_b = context.config.connections[request.serial_b_connection_id]
        host = str(serial_b.parameters["host"])
        port = int(serial_b.parameters["port"])
        collector = self.services.serial_collector_factory(
            host, port, context.directory / "serial_b.raw.log"
        )
        if not bool(getattr(collector, "required", False)):
            raise TypeError("DV serial_b collector must be marked required")
        return (collector,)

    def build_initialize_plan(self, context: ControlContext) -> Plan:
        request = self._request(context.config)
        provider = self.services.providers.resolve(request.provider_id)
        state = DvExecutionState(request)
        self._state = state
        self._provider = provider
        return build_dv_initialize_plan(state, provider)

    async def verify_ready(self, context: ControlContext) -> ReadinessResult:
        state, provider = self._active()
        for endpoint in (DvSshEndpoint.LINUX, DvSshEndpoint.ACCELERATOR):
            result = await provider.probe_ssh(
                endpoint, DvActionContext(state.request, context, state)
            )
            if not hasattr(result, "status") or result.status is not StepStatus.SUCCEEDED:
                summary = getattr(result, "summary", f"{endpoint.value} SSH is not ready")
                return ReadinessResult(False, summary, {"endpoint": endpoint.value})
        result = await asyncio.wait_for(
            provider.verify_ready(DvActionContext(state.request, context, state)),
            timeout=600,
        )
        if not isinstance(result, ReadinessResult):
            raise TypeError("DV provider verify_ready() must return ReadinessResult")
        return result

    async def collect_failure_context(self, context: ControlContext, failure: Any) -> None:
        if self._state is None or self._state.interactive is None:
            return
        close = getattr(self._state.interactive, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass

    def _active(self) -> tuple[DvExecutionState, DvContributionProvider]:
        if self._state is None or self._provider is None:
            raise RuntimeError("DV initialization state is unavailable")
        return self._state, self._provider

    def _request(self, config: EffectiveEnvironmentConfig) -> DvRunRequest:
        dv = self._mapping(config.raw, "dv")
        provider_id = self._text(dv, "provider_id")
        return DvRunRequest(
            config.environment_id,
            provider_id,
            self._connection_for_role(config, "linux_bmc").connection_id,
            self._connection_for_role(config, "serial_a").connection_id,
            self._connection_for_role(config, "serial_b").connection_id,
            self._connection_for_role(config, "linux_ssh").connection_id,
            self._connection_for_role(config, "accelerator_ssh").connection_id,
            config.raw,
        )

    @staticmethod
    def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        item = value.get(key)
        if not isinstance(item, Mapping):
            raise ValueError(f"DV config needs a {key!r} mapping")
        return item

    @staticmethod
    def _text(value: Mapping[str, Any], key: str) -> str:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"DV config needs non-empty {key!r}")
        return item.strip()

    @staticmethod
    def _connection_for_role(config: EffectiveEnvironmentConfig, role: str):
        matches = [
            item for item in config.connections.values() if item.enabled and item.role == role
        ]
        if len(matches) != 1:
            raise ValueError(f"DV config needs exactly one enabled {role!r} connection")
        return matches[0]
