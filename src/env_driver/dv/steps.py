"""Public DV steps wrapping connectors and sensitive provider operations."""
from __future__ import annotations

import asyncio

from basic_connector.bmc_connector import IssuePolicy, PowerOperationStatus, PowerState

from ..core.steps import CheckStep, OperationStep
from ..core.types import SideEffect, StepResult, StepStatus
from .contract import DvContributionProvider
from .types import (
    DvActionContext,
    DvActionDefinition,
    DvExecutionState,
    DvPowerAction,
    DvSshEndpoint,
)


def _provider_context(state: DvExecutionState, control) -> DvActionContext:
    return DvActionContext(state.request, control, state)


class CheckBmcStep(CheckStep):
    def __init__(self, state: DvExecutionState) -> None:
        super().__init__("0.1.bmc.check", "检查Linux BMC", timeout=30)
        self.state = state

    async def check(self, context) -> StepResult:
        connector = context.resolve_connection(
            self.state.request.bmc_connection_id, connector_type="bmc"
        )
        state = await connector.get_power_state()
        if not isinstance(state, PowerState):
            raise TypeError("BMC get_power_state() must return PowerState")
        return StepResult.success(
            "Linux BMC is reachable",
            details={"power_state": state.value},
        )


class ConnectSerialStep(OperationStep):
    def __init__(self, step_id: str, title: str, connection_id: str) -> None:
        super().__init__(
            step_id,
            title,
            timeout=30,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.connection_id = connection_id

    async def perform(self, context) -> StepResult:
        connector = context.resolve_connection(self.connection_id, connector_type="serial")
        await connector.connect()
        return StepResult.success("serial control connection is ready")


class LinuxPowerStep(OperationStep):
    def __init__(self, state: DvExecutionState, *, power_on: bool) -> None:
        step_id = "1.4.power.linux.on" if power_on else "1.1.power.linux.force_off"
        title = "上电Linux服务器" if power_on else "强制下电Linux服务器"
        super().__init__(step_id, title, timeout=300, side_effect=SideEffect.DESTRUCTIVE)
        self.state = state
        self.power_on = power_on

    async def perform(self, context) -> StepResult:
        connector = context.resolve_connection(
            self.state.request.bmc_connection_id, connector_type="bmc"
        )
        result = (
            await connector.power_on(issue_policy=IssuePolicy.ALWAYS)
            if self.power_on
            else await connector.force_off(issue_policy=IssuePolicy.ALWAYS)
        )
        if result.status is PowerOperationStatus.SUCCEEDED:
            return StepResult.success(
                result.diagnostic_summary,
                changed=result.changed,
                details={
                    "action_issued": result.action_issued,
                    "verified": result.verified,
                    "final_state": result.final_state.value,
                },
            )
        status = (
            StepStatus.UNKNOWN
            if result.status is PowerOperationStatus.UNKNOWN
            else StepStatus.FAILED
        )
        return StepResult(
            status,
            result.diagnostic_summary,
            changed=result.changed,
            details={"bmc_status": result.status.value},
        )


class AcceleratorPowerStep(OperationStep):
    def __init__(
        self,
        state: DvExecutionState,
        provider: DvContributionProvider,
        action: DvPowerAction,
    ) -> None:
        power_on = action is DvPowerAction.ACCELERATOR_POWER_ON
        super().__init__(
            "1.3.power.accelerator.on" if power_on else "1.2.power.accelerator.force_off",
            "上电异构计算机" if power_on else "下电异构计算机",
            timeout=300,
            side_effect=SideEffect.DESTRUCTIVE,
        )
        self.state = state
        self.provider = provider
        self.action = action

    async def perform(self, context) -> StepResult:
        result = await self.provider.execute_power_action(
            self.action, _provider_context(self.state, context)
        )
        if not isinstance(result, StepResult):
            raise TypeError("DV provider execute_power_action() must return StepResult")
        return result


class ProviderActionStep(OperationStep):
    def __init__(
        self,
        definition: DvActionDefinition,
        state: DvExecutionState,
        provider: DvContributionProvider,
    ) -> None:
        prefix = "2" if definition.phase.value == "serial_prepare" else "4"
        super().__init__(
            f"{prefix}.provider.{definition.phase.value}.{definition.action_id}",
            definition.title,
            timeout=definition.timeout,
            side_effect=definition.side_effect,
        )
        self.definition = definition
        self.state = state
        self.provider = provider

    async def perform(self, context) -> StepResult:
        result = await self.provider.execute_action(
            self.definition.action_id,
            _provider_context(self.state, context),
        )
        if not isinstance(result, StepResult):
            raise TypeError("DV provider execute_action() must return StepResult")
        return result


class WaitForSshStep(CheckStep):
    def __init__(
        self,
        state: DvExecutionState,
        provider: DvContributionProvider,
        endpoint: DvSshEndpoint,
        *,
        poll_interval: float = 10.0,
    ) -> None:
        linux = endpoint is DvSshEndpoint.LINUX
        super().__init__(
            "3.1.ssh.linux.wait_ready" if linux else "3.2.ssh.accelerator.wait_ready",
            "等待Linux SSH就绪" if linux else "等待异构计算机跳转SSH就绪",
            timeout=1200 if linux else 600,
        )
        self.state = state
        self.provider = provider
        self.endpoint = endpoint
        self.poll_interval = poll_interval

    async def check(self, context) -> StepResult:
        attempts = 0
        last_summary = "SSH is not ready"
        while True:
            attempts += 1
            try:
                await self._connect(context)
                result = await self.provider.probe_ssh(
                    self.endpoint, _provider_context(self.state, context)
                )
                if not isinstance(result, StepResult):
                    raise TypeError("DV provider probe_ssh() must return StepResult")
                last_summary = result.summary
                if result.status is StepStatus.SUCCEEDED:
                    return StepResult.success(
                        result.summary,
                        details={
                            "endpoint": self.endpoint.value,
                            "attempts": attempts,
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_summary = f"{type(exc).__name__}: SSH is not ready"
            if context.cancel_event.is_set():
                raise asyncio.CancelledError
            await asyncio.sleep(self.poll_interval)

    async def _connect(self, context):
        request = self.state.request
        if self.endpoint is DvSshEndpoint.LINUX:
            session = context.resolve_connection(
                request.linux_ssh_connection_id, connector_type="ssh"
            )
            await session.connect()
            return session
        parent = context.resolve_connection(
            request.linux_ssh_connection_id, connector_type="ssh"
        )
        session = context.resolve_connection(
            request.accelerator_ssh_connection_id, connector_type="ssh"
        )
        await parent.connect()
        await session.connect_via(parent)
        self.state.accelerator_tunnel_bound = True
        return session
