from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class PowerState(str, Enum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class PowerAction(str, Enum):
    POWER_ON = "power_on"
    FORCE_OFF = "force_off"


class IssuePolicy(str, Enum):
    IF_NEEDED = "if_needed"
    ALWAYS = "always"


class PowerOperationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PowerActionReceipt:
    accepted: bool
    diagnostic_summary: str = ""


@dataclass(frozen=True)
class PowerOperationResult:
    requested_action: PowerAction
    previous_state: PowerState
    final_state: PowerState
    status: PowerOperationStatus
    backend: str
    action_issued: bool
    action_accepted: bool | None
    verified: bool
    changed: bool
    diagnostic_summary: str
    started_at: datetime
    finished_at: datetime

    @property
    def succeeded(self) -> bool:
        return self.status is PowerOperationStatus.SUCCEEDED


@dataclass(frozen=True)
class BiosSnapshot:
    system_id: str
    attributes: Mapping[str, Any]
    backend: str
    captured_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
