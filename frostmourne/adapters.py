"""Internal teams register trusted Python adapters here, never import code from a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol

from .models import Environment


@dataclass(frozen=True)
class AdapterResult:
    ready: bool
    summary: str
    action_state: str = "completed"


class Adapter(Protocol):
    def initialize(self, environment: Environment, settings: dict[str, str],
                   emit: Callable[[int, str], None], cancel: Event) -> AdapterResult:
        """Must verify identity, honor safe cancellation, and perform final readiness checks.

        Raising leaves the remote action state UNKNOWN. Never assume cancelling a local
        thread cancels flashing. Emit only sanitized messages; no credentials or secrets.
        """
        ...


# Register internal, reviewed implementations here. The public shell has none.
ADAPTERS: dict[str, Adapter] = {}
