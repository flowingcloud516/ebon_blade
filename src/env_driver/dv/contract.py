"""Contract implemented by the sensitive DV contribution."""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..core.types import ReadinessResult, StepResult, ValidationReport
from .types import (
    _ID,
    DvActionContext,
    DvActionDefinition,
    DvPhase,
    DvPowerAction,
    DvRunRequest,
    DvSshEndpoint,
)


@runtime_checkable
class DvContributionProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def validate(self, request: DvRunRequest) -> ValidationReport: ...

    def actions(self, phase: DvPhase) -> tuple[DvActionDefinition, ...]: ...

    async def execute_power_action(
        self,
        action: DvPowerAction,
        context: DvActionContext,
    ) -> StepResult: ...

    async def probe_ssh(
        self,
        endpoint: DvSshEndpoint,
        context: DvActionContext,
    ) -> StepResult: ...

    async def execute_action(
        self,
        action_id: str,
        context: DvActionContext,
    ) -> StepResult: ...

    async def verify_ready(self, context: DvActionContext) -> ReadinessResult: ...


ProviderFactory = Callable[[], DvContributionProvider]


class DvProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        if not _ID.fullmatch(provider_id):
            raise ValueError(f"invalid DV provider ID: {provider_id!r}")
        if provider_id in self._factories:
            raise ValueError(f"DV provider already registered: {provider_id}")
        provider = factory()
        if not isinstance(provider, DvContributionProvider):
            raise TypeError("factory must return a DvContributionProvider")
        if provider.provider_id != provider_id:
            raise ValueError("registered provider ID does not match provider.provider_id")
        self._factories[provider_id] = factory

    def resolve(self, provider_id: str) -> DvContributionProvider:
        factory = self._factories.get(provider_id)
        if factory is None:
            raise KeyError(f"DV contribution provider is not registered: {provider_id}")
        provider = factory()
        if not isinstance(provider, DvContributionProvider):
            raise TypeError("registered factory stopped returning DvContributionProvider")
        return provider

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
