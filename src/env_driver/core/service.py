"""Application service coordinating validation, logging and control scopes."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import asyncio
import inspect
from pathlib import Path
from typing import Any

from .context import ControlContext
from .executor import PlanExecutor
from .logs import LogContext, LogManager
from .registry import EnvironmentRegistry
from .types import (
    ActionState,
    ConnectionConfig,
    EffectiveEnvironmentConfig,
    EnvironmentResult,
    EnvironmentStatus,
    ValidationIssue,
    ValidationReport,
)


ConnectorFactory = Callable[[ConnectionConfig], Any | Awaitable[Any]]


class EnvironmentControlService:
    def __init__(
        self,
        registry: EnvironmentRegistry,
        *,
        executor: PlanExecutor | None = None,
        log_manager: LogManager | None = None,
        run_directory: Path | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor or PlanExecutor()
        self.log_manager = log_manager or LogManager()
        self.run_directory = run_directory

    async def initialize(
        self,
        config: EffectiveEnvironmentConfig | Mapping[str, Any],
        *,
        connector_factory: ConnectorFactory,
        dependency_results: Mapping[str, EnvironmentResult] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> EnvironmentResult:
        if not isinstance(config, EffectiveEnvironmentConfig):
            config = EffectiveEnvironmentConfig.from_mapping(config)
        driver = self.registry.resolve(config.type_id)

        report = self._validate_connections(driver.definition(), config)
        try:
            driver_report = driver.validate_config(config)
        except Exception as exc:
            driver_report = ValidationReport.failure(
                "driver_validation_failed",
                f"environment validation raised {type(exc).__name__}",
                "environment",
            )
        if not isinstance(driver_report, ValidationReport):
            raise TypeError("validate_config() must return ValidationReport")
        report = report.combined(driver_report)
        if not report.valid:
            return self._preflight_failure(config, EnvironmentStatus.FAILED, report)

        missing = []
        known_results = dependency_results or {}
        for dependency in driver.dependencies(config):
            result = known_results.get(dependency.environment_id)
            matches = result is not None and (
                result.ready
                if dependency.required_state == "ready"
                else result.status.value == dependency.required_state
            )
            if not matches:
                missing.append(dependency.environment_id)
        if missing:
            return EnvironmentResult(
                config.environment_id,
                EnvironmentStatus.BLOCKED,
                False,
                "blocked by dependencies: " + ", ".join(missing),
                ActionState.NOT_STARTED,
            )

        log_directory = (
            self.run_directory / "env" / config.environment_id / "collectors"
            if self.run_directory is not None
            else None
        )
        log_session = self.log_manager.get(config.environment_id)
        if log_session is None:
            try:
                if log_directory is not None:
                    log_directory.mkdir(parents=True, exist_ok=True)
                log_context = LogContext(config.environment_id, config, log_directory)
                collectors = driver.create_log_collectors(log_context)
                log_session = await self.log_manager.start_environment_log_session(
                    config.environment_id, tuple(collectors)
                )
            except Exception as exc:
                return EnvironmentResult(
                    config.environment_id,
                    EnvironmentStatus.FAILED,
                    False,
                    f"environment log setup failed: {type(exc).__name__}",
                    ActionState.NOT_STARTED,
                )
        if log_session.required_start_errors:
            return EnvironmentResult(
                config.environment_id,
                EnvironmentStatus.FAILED,
                False,
                "required environment log collector failed to start",
                ActionState.NOT_STARTED,
            )

        connectors: dict[str, Any] = {}
        context: ControlContext | None = None
        try:
            for connection_id, connection in config.connections.items():
                if not connection.enabled:
                    continue
                connector = connector_factory(connection)
                if inspect.isawaitable(connector):
                    connector = await connector
                connectors[connection_id] = connector
            control_directory = (
                self.run_directory / "env" / config.environment_id / "control"
                if self.run_directory is not None
                else None
            )
            if control_directory is not None:
                control_directory.mkdir(parents=True, exist_ok=True)
            context = ControlContext(
                config,
                connectors,
                cancel_event=cancel_event,
                run_directory=control_directory,
            )
            plan = driver.build_initialize_plan(context)
            return await self.executor.execute(driver, plan, context)
        except Exception as exc:
            return EnvironmentResult(
                config.environment_id,
                EnvironmentStatus.FAILED,
                False,
                f"initialization setup failed: {exc}",
                ActionState.NOT_STARTED,
            )
        finally:
            if context is not None:
                await context.close()
            else:
                await self._close_connectors(connectors)

    async def finish_run(self) -> None:
        """Explicitly close all long-running log sessions."""
        await self.log_manager.stop_all()

    @staticmethod
    def _validate_connections(definition, config) -> ValidationReport:
        issues: list[ValidationIssue] = []
        enabled = [item for item in config.connections.values() if item.enabled]
        for requirement in definition.connection_requirements:
            by_role = [item for item in enabled if item.role == requirement.role]
            wrong_type = [
                item for item in by_role if item.connector_type != requirement.connector_type
            ]
            valid = [
                item for item in by_role if item.connector_type == requirement.connector_type
            ]
            if wrong_type:
                issues.append(
                    ValidationIssue(
                        "connection_type_mismatch",
                        f"role {requirement.role!r} requires {requirement.connector_type!r}",
                        "connections",
                    )
                )
            if len(valid) < requirement.min_count:
                issues.append(
                    ValidationIssue(
                        "connection_count_too_low",
                        f"role {requirement.role!r} needs at least {requirement.min_count}",
                        "connections",
                    )
                )
            if requirement.max_count is not None and len(valid) > requirement.max_count:
                issues.append(
                    ValidationIssue(
                        "connection_count_too_high",
                        f"role {requirement.role!r} allows at most {requirement.max_count}",
                        "connections",
                    )
                )
        return ValidationReport(tuple(issues))

    @staticmethod
    def _preflight_failure(config, status, report) -> EnvironmentResult:
        return EnvironmentResult(
            config.environment_id,
            status,
            False,
            "; ".join(issue.message for issue in report.issues),
            ActionState.NOT_STARTED,
        )

    @staticmethod
    async def _close_connectors(connectors: Mapping[str, Any]) -> None:
        seen: set[int] = set()
        for connector in reversed(tuple(connectors.values())):
            if id(connector) in seen:
                continue
            seen.add(id(connector))
            close = getattr(connector, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
