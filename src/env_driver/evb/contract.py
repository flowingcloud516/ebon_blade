"""Contract implemented by the EVB-specific internal contribution."""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..core.logs import LogCollector, LogContext
from ..core.types import ReadinessResult, StepResult, ValidationReport
from .filezilla import WorkspaceArtifactLayout
from .types import (
    _ID,
    EvbActionContext,
    EvbActionDefinition,
    EvbArtifactLayout,
    EvbDeploymentLayout,
    EvbLogActivation,
    EvbPhase,
    EvbRunRequest,
)


@runtime_checkable
class EvbContributionProvider(Protocol):
    """Provide device-specific facts and actions to the public EVB driver."""

    @property
    def provider_id(self) -> str: ...

    def validate(self, request: EvbRunRequest) -> ValidationReport: ...

    def artifact_layout(self, request: EvbRunRequest) -> EvbArtifactLayout: ...

    def workspace_layout(self, request: EvbRunRequest) -> WorkspaceArtifactLayout: ...

    def deployment_layout(self, request: EvbRunRequest) -> EvbDeploymentLayout: ...

    def actions(self, phase: EvbPhase) -> tuple[EvbActionDefinition, ...]: ...

    def create_log_collectors(
        self,
        request: EvbRunRequest,
        context: LogContext,
        activation: EvbLogActivation,
    ) -> tuple[LogCollector, ...]: ...

    async def execute_action(
        self,
        action_id: str,
        context: EvbActionContext,
    ) -> StepResult: ...

    async def verify_ready(self, context: EvbActionContext) -> ReadinessResult: ...


ProviderFactory = Callable[[], EvbContributionProvider]


class EvbProviderRegistry:
    """Explicit registry for the EVB contribution available in this checkout."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        if not _ID.fullmatch(provider_id):
            raise ValueError(f"invalid provider ID: {provider_id!r}")
        if provider_id in self._factories:
            raise ValueError(f"EVB provider already registered: {provider_id}")
        provider = factory()
        if not isinstance(provider, EvbContributionProvider):
            raise TypeError("factory must return an EvbContributionProvider")
        if provider.provider_id != provider_id:
            raise ValueError("registered provider ID does not match provider.provider_id")
        self._factories[provider_id] = factory

    def resolve(self, provider_id: str) -> EvbContributionProvider:
        factory = self._factories.get(provider_id)
        if factory is None:
            raise KeyError(f"EVB contribution provider is not registered: {provider_id}")
        provider = factory()
        if not isinstance(provider, EvbContributionProvider):
            raise TypeError("registered factory stopped returning EvbContributionProvider")
        return provider

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
