"""Public value objects shared by the DV driver and internal provider."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

from ..core.context import ControlContext
from ..core.types import SideEffect


_ID = re.compile(r"^[a-z][a-z0-9_.-]*$")


class DvPhase(str, Enum):
    SERIAL_PREPARE = "serial_prepare"
    SSH_OPERATE = "ssh_operate"


class DvPowerAction(str, Enum):
    ACCELERATOR_FORCE_OFF = "accelerator_force_off"
    ACCELERATOR_POWER_ON = "accelerator_power_on"


class DvSshEndpoint(str, Enum):
    LINUX = "linux"
    ACCELERATOR = "accelerator"


@dataclass(frozen=True)
class DvActionDefinition:
    action_id: str
    title: str
    phase: DvPhase
    side_effect: SideEffect
    timeout: float
    success_evidence: str
    failure_evidence: str
    cancellation_policy: str

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.action_id):
            raise ValueError(f"invalid DV action ID: {self.action_id!r}")
        if not self.title.strip() or self.timeout <= 0:
            raise ValueError("DV action title and positive timeout are required")
        if not isinstance(self.phase, DvPhase) or not isinstance(self.side_effect, SideEffect):
            raise TypeError("DV action phase and side_effect must use public enums")
        if self.side_effect is SideEffect.READ_ONLY:
            raise ValueError("DV provider actions must represent explicit operations")
        if not all(
            value.strip()
            for value in (
                self.success_evidence,
                self.failure_evidence,
                self.cancellation_policy,
            )
        ):
            raise ValueError("DV actions must document success, failure and cancellation")


@dataclass(frozen=True)
class DvRunRequest:
    environment_id: str
    provider_id: str
    bmc_connection_id: str
    serial_a_connection_id: str
    serial_b_connection_id: str
    linux_ssh_connection_id: str
    accelerator_ssh_connection_id: str
    config: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.provider_id):
            raise ValueError(f"invalid DV provider ID: {self.provider_id!r}")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass
class DvExecutionState:
    request: DvRunRequest
    accelerator_tunnel_bound: bool = False
    interactive: Any | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DvActionContext:
    request: DvRunRequest
    control: ControlContext
    state: DvExecutionState
