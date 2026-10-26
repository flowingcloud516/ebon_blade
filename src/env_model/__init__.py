"""Public environment-model framework API."""

from .context import ControlContext
from .errors import (
    ConfigurationError,
    ContextClosedError,
    DefinitionError,
    EnvironmentFrameworkError,
    RegistryError,
    StepCancelledError,
    StepStateUnknownError,
)
from .executor import PlanExecutor
from .logs import LogCollector, LogContext, LogManager, LogSession
from .model import EnvironmentModel
from .plan import Phase, Plan
from .registry import EnvironmentRegistry
from .service import ConnectorFactory, EnvironmentControlService
from .steps import CheckStep, EnsureStateStep, OperationStep, Step
from .types import (
    ActionState,
    ConnectionConfig,
    ConnectionRequirement,
    Dependency,
    EffectiveEnvironmentConfig,
    EnvironmentDefinition,
    EnvironmentResult,
    EnvironmentStatus,
    FailurePolicy,
    PhaseResult,
    ReadinessResult,
    RetryPolicy,
    SideEffect,
    StateObservation,
    StepRecord,
    StepResult,
    StepStatus,
    ValidationIssue,
    ValidationReport,
)

__all__ = [
    "ActionState",
    "CheckStep",
    "ConfigurationError",
    "ConnectionConfig",
    "ConnectionRequirement",
    "ConnectorFactory",
    "ContextClosedError",
    "ControlContext",
    "DefinitionError",
    "Dependency",
    "EffectiveEnvironmentConfig",
    "EnsureStateStep",
    "EnvironmentControlService",
    "EnvironmentDefinition",
    "EnvironmentFrameworkError",
    "EnvironmentModel",
    "EnvironmentRegistry",
    "EnvironmentResult",
    "EnvironmentStatus",
    "FailurePolicy",
    "LogCollector",
    "LogContext",
    "LogManager",
    "LogSession",
    "OperationStep",
    "Phase",
    "PhaseResult",
    "Plan",
    "PlanExecutor",
    "ReadinessResult",
    "RegistryError",
    "RetryPolicy",
    "SideEffect",
    "StateObservation",
    "Step",
    "StepCancelledError",
    "StepRecord",
    "StepResult",
    "StepStateUnknownError",
    "StepStatus",
    "ValidationIssue",
    "ValidationReport",
]
