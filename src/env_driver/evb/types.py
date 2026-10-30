"""Public value objects used by the EVB driver and its internal provider."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping

from ..core.context import ControlContext
from ..core.types import SideEffect
from .filezilla import (
    FileZillaRootLease,
    FileZillaRootManager,
    ResolvedWorkspaceArtifactLayout,
)


_ID = re.compile(r"^[a-z][a-z0-9_.-]*$")


class EvbPhase(str, Enum):
    CONFIGURE = "configure"
    START = "start"
    OPERATE = "operate"


@dataclass(frozen=True)
class EvbArtifactLayout:
    firmware: str
    boot_script: str
    driver: str
    third_party: str

    def __post_init__(self) -> None:
        for label, value in (
            ("firmware", self.firmware),
            ("boot_script", self.boot_script),
            ("driver", self.driver),
            ("third_party", self.third_party),
        ):
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe {label} artifact path: {value!r}")


@dataclass(frozen=True)
class EvbDeploymentLayout:
    driver_remote_path: str
    third_party_remote_path: str

    def __post_init__(self) -> None:
        for label, value in (
            ("driver_remote_path", self.driver_remote_path),
            ("third_party_remote_path", self.third_party_remote_path),
        ):
            path = PurePosixPath(value)
            if not value or not path.is_absolute() or ".." in path.parts:
                raise ValueError(f"{label} must be a safe absolute POSIX path")


@dataclass(frozen=True)
class EvbActionDefinition:
    action_id: str
    title: str
    phase: EvbPhase
    side_effect: SideEffect
    timeout: float
    success_evidence: str
    failure_evidence: str
    cancellation_policy: str

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.action_id):
            raise ValueError(f"invalid EVB action ID: {self.action_id!r}")
        if not self.title.strip() or self.timeout <= 0:
            raise ValueError("EVB action title and positive timeout are required")
        if not isinstance(self.phase, EvbPhase) or not isinstance(self.side_effect, SideEffect):
            raise TypeError("EVB action phase and side_effect must use public enums")
        if (
            not self.success_evidence.strip()
            or not self.failure_evidence.strip()
            or not self.cancellation_policy.strip()
        ):
            raise ValueError("EVB actions must document success, failure and cancellation")


@dataclass(frozen=True)
class EvbRunRequest:
    environment_id: str
    platform: str
    version: str
    provider_id: str
    workspace_root: Path
    filezilla_root: Path
    ssh_connection_id: str
    config: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", self.workspace_root.resolve())
        object.__setattr__(self, "filezilla_root", self.filezilla_root.resolve())
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass(frozen=True)
class EvbArtifactBundle:
    root: Path
    firmware: Path
    boot_script: Path
    driver: Path
    third_party: Path
    reused_in_run: bool = False


@dataclass
class EvbExecutionState:
    request: EvbRunRequest
    log_activation: "EvbLogActivation"
    bundle: EvbArtifactBundle | None = None
    workspace_layout: ResolvedWorkspaceArtifactLayout | None = None
    filezilla_manager: FileZillaRootManager | None = None
    filezilla_lease: FileZillaRootLease | None = None
    start_action_started: bool = False
    start_phase_completed: bool = False


@dataclass(frozen=True)
class EvbActionContext:
    request: EvbRunRequest
    artifacts: EvbArtifactBundle
    control: ControlContext
    workspace_layout: ResolvedWorkspaceArtifactLayout | None = None


@dataclass(frozen=True)
class EvbLogActivation:
    """Core-owned gate preventing EVB SSH logging before SSH is proven ready."""

    evb_ssh_ready: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def wait_for_evb_ssh(self) -> None:
        await self.evb_ssh_ready.wait()
