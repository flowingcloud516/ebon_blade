"""Extension contract implemented by concrete environment types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .context import ControlContext
from .logs import LogCollector, LogContext
from .plan import Plan
from .types import (
    Dependency,
    EffectiveEnvironmentConfig,
    EnvironmentDefinition,
    ReadinessResult,
    ValidationReport,
)


class EnvironmentModel(ABC):
    @classmethod
    @abstractmethod
    def definition(cls) -> EnvironmentDefinition:
        """Return immutable, device-independent type metadata."""

    @abstractmethod
    def validate_config(self, config: EffectiveEnvironmentConfig) -> ValidationReport:
        """Return all discoverable semantic configuration issues."""

    @abstractmethod
    def dependencies(self, config: EffectiveEnvironmentConfig) -> tuple[Dependency, ...]:
        """Declare dependencies without starting them."""

    @abstractmethod
    def create_log_collectors(self, context: LogContext) -> tuple[LogCollector, ...]:
        """Create collectors with resources independent of ControlContext."""

    @abstractmethod
    def build_initialize_plan(self, context: ControlContext) -> Plan:
        """Describe the plan without performing device operations."""

    @abstractmethod
    async def verify_ready(self, context: ControlContext) -> ReadinessResult:
        """Independently verify final environment readiness."""

    async def collect_failure_context(
        self,
        context: ControlContext,
        failure: Any,
    ) -> None:
        """Optional bounded, read-only diagnostics hook."""
        return None
