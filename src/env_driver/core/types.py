"""Stable value types shared by environment models and the public executor."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, TYPE_CHECKING

from .errors import ConfigurationError, DefinitionError

if TYPE_CHECKING:
    from .steps import Step


_TYPE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _require_id(value: str, name: str, *, type_id: bool = False) -> None:
    pattern = _TYPE_ID if type_id else _ITEM_ID
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise DefinitionError(f"invalid {name}: {value!r}")


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class EnvironmentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class ActionState(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class SideEffect(str, Enum):
    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    DESTRUCTIVE = "destructive"
    EXTERNAL_UNKNOWN = "external_unknown"


class FailurePolicy(str, Enum):
    STOP_PLAN = "stop_plan"
    CONTINUE = "continue"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    delays: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise DefinitionError("max_attempts must be at least one")
        if any(delay < 0 for delay in self.delays):
            raise DefinitionError("retry delays must not be negative")
        if self.max_attempts > 1 and len(self.delays) not in {0, self.max_attempts - 1}:
            raise DefinitionError("retry delays must be empty or have max_attempts - 1 entries")

    def delay_before(self, attempt: int) -> float:
        """Return the delay before a one-based retry attempt."""
        if attempt <= 1 or not self.delays:
            return 0.0
        return self.delays[attempt - 2]


@dataclass(frozen=True)
class ConnectionRequirement:
    role: str
    connector_type: str
    min_count: int = 1
    max_count: int | None = 1

    def __post_init__(self) -> None:
        _require_id(self.role, "connection role")
        _require_id(self.connector_type, "connector type", type_id=True)
        if self.min_count < 0:
            raise DefinitionError("connection min_count must not be negative")
        if self.max_count is not None and self.max_count < self.min_count:
            raise DefinitionError("connection max_count must be >= min_count")


@dataclass(frozen=True)
class EnvironmentDefinition:
    type_id: str
    display_name: str
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    connection_requirements: tuple[ConnectionRequirement, ...] = ()
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_id(self.type_id, "environment type", type_id=True)
        if not self.display_name.strip():
            raise DefinitionError("display_name must not be empty")
        roles = [item.role for item in self.connection_requirements]
        if len(set(roles)) != len(roles):
            raise DefinitionError("connection requirement roles must be unique")
        object.__setattr__(self, "config_schema", _mapping(self.config_schema))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))


@dataclass(frozen=True)
class ConnectionConfig:
    connection_id: str
    connector_type: str
    role: str
    enabled: bool = True
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.connection_id, "connection_id")
        _require_id(self.connector_type, "connector type", type_id=True)
        _require_id(self.role, "connection role")
        object.__setattr__(self, "parameters", _mapping(self.parameters))

    @classmethod
    def from_mapping(cls, connection_id: str, value: Mapping[str, Any]) -> "ConnectionConfig":
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"connection {connection_id!r} must be a mapping")
        connector_type = value.get("type")
        role = value.get("role")
        if not isinstance(connector_type, str) or not isinstance(role, str):
            raise ConfigurationError(f"connection {connection_id!r} needs string type and role")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigurationError(f"connection {connection_id!r} enabled must be boolean")
        parameters = {key: item for key, item in value.items()
                      if key not in {"type", "role", "enabled"}}
        try:
            return cls(connection_id, connector_type, role, enabled, parameters)
        except DefinitionError as exc:
            raise ConfigurationError(str(exc)) from exc


@dataclass(frozen=True)
class EffectiveEnvironmentConfig:
    environment_id: str
    type_id: str
    name: str
    connections: Mapping[str, ConnectionConfig] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        try:
            _require_id(self.environment_id, "environment_id")
            _require_id(self.type_id, "environment type", type_id=True)
        except DefinitionError as exc:
            raise ConfigurationError(str(exc)) from exc
        if not self.name.strip():
            raise ConfigurationError("environment name must not be empty")
        normalized = dict(self.connections)
        if any(key != value.connection_id for key, value in normalized.items()):
            raise ConfigurationError("connection mapping keys must match connection_id")
        object.__setattr__(self, "connections", MappingProxyType(normalized))
        object.__setattr__(self, "raw", _mapping(self.raw))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EffectiveEnvironmentConfig":
        if not isinstance(value, Mapping):
            raise ConfigurationError("environment config must be a mapping")
        environment = value.get("environment")
        if not isinstance(environment, Mapping):
            raise ConfigurationError("environment section must be a mapping")
        raw_connections = value.get("connections", {})
        if not isinstance(raw_connections, Mapping):
            raise ConfigurationError("connections must be a mapping")
        connections = {
            connection_id: ConnectionConfig.from_mapping(connection_id, item)
            for connection_id, item in raw_connections.items()
        }
        try:
            return cls(
                environment_id=environment["id"],
                type_id=environment["type"],
                name=environment["name"],
                connections=connections,
                raw=value,
            )
        except KeyError as exc:
            raise ConfigurationError(f"missing environment field: {exc.args[0]}") from exc


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        if not self.code or not self.message:
            raise DefinitionError("validation issue code and message are required")


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    @classmethod
    def success(cls) -> "ValidationReport":
        return cls()

    @classmethod
    def failure(cls, code: str, message: str, field: str | None = None) -> "ValidationReport":
        return cls((ValidationIssue(code, message, field),))

    def combined(self, other: "ValidationReport") -> "ValidationReport":
        return ValidationReport(self.issues + other.issues)


@dataclass(frozen=True)
class Dependency:
    environment_id: str
    required_state: str = "ready"

    def __post_init__(self) -> None:
        _require_id(self.environment_id, "dependency environment_id")
        if not self.required_state:
            raise DefinitionError("dependency required_state must not be empty")


@dataclass(frozen=True)
class StateObservation:
    satisfied: bool
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _mapping(self.details))


@dataclass(frozen=True)
class StepResult:
    status: StepStatus
    summary: str
    changed: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    attempts: int = 1

    def __post_init__(self) -> None:
        if self.status in {StepStatus.PENDING, StepStatus.RUNNING}:
            raise DefinitionError(f"{self.status.value} is not a terminal StepResult status")
        if self.attempts < 1:
            raise DefinitionError("attempts must be positive")
        object.__setattr__(self, "details", _mapping(self.details))

    @classmethod
    def success(cls, summary: str, *, changed: bool = False,
                details: Mapping[str, Any] | None = None) -> "StepResult":
        return cls(StepStatus.SUCCEEDED, summary, changed, details or {})


@dataclass(frozen=True)
class StepRecord:
    step_id: str
    title: str
    result: StepResult


@dataclass(frozen=True)
class PhaseResult:
    phase_id: str
    title: str
    status: StepStatus
    steps: tuple[StepRecord, ...]


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _mapping(self.details))


@dataclass(frozen=True)
class EnvironmentResult:
    environment_id: str
    status: EnvironmentStatus
    ready: bool
    summary: str
    action_state: ActionState
    phases: tuple[PhaseResult, ...] = ()
    readiness: ReadinessResult | None = None

    def __post_init__(self) -> None:
        if self.ready and self.status is not EnvironmentStatus.SUCCEEDED:
            raise DefinitionError("only a succeeded environment result can be ready")
        if self.ready and self.action_state is not ActionState.COMPLETED:
            raise DefinitionError("an environment cannot be ready while action state is not completed")
