"""Fixed public DV phase and step ordering."""
from __future__ import annotations

from ..core.plan import Phase, Plan
from .contract import DvContributionProvider
from .steps import (
    AcceleratorPowerStep,
    CheckBmcStep,
    ConnectSerialStep,
    LinuxPowerStep,
    ProviderActionStep,
    WaitForSshStep,
)
from .types import DvExecutionState, DvPhase, DvPowerAction, DvSshEndpoint


def build_dv_initialize_plan(
    state: DvExecutionState,
    provider: DvContributionProvider,
) -> Plan:
    request = state.request
    precheck = Phase(
        "precheck",
        "前置检查",
        (
            CheckBmcStep(state),
            ConnectSerialStep("0.2.serial_a.connect", "连接串口A控制会话", request.serial_a_connection_id),
            ConnectSerialStep("0.3.serial_b.connect", "连接串口B控制会话", request.serial_b_connection_id),
        ),
    )
    power_cycle = Phase(
        "power_cycle",
        "严格电源循环",
        (
            LinuxPowerStep(state, power_on=False),
            AcceleratorPowerStep(
                state, provider, DvPowerAction.ACCELERATOR_FORCE_OFF
            ),
            AcceleratorPowerStep(
                state, provider, DvPowerAction.ACCELERATOR_POWER_ON
            ),
            LinuxPowerStep(state, power_on=True),
        ),
    )
    serial_prepare = Phase(
        "serial_prepare",
        "串口网络准备",
        tuple(
            ProviderActionStep(action, state, provider)
            for action in provider.actions(DvPhase.SERIAL_PREPARE)
        ),
    )
    wait_ssh = Phase(
        "wait_ssh",
        "等待两层SSH",
        (
            WaitForSshStep(state, provider, DvSshEndpoint.LINUX),
            WaitForSshStep(state, provider, DvSshEndpoint.ACCELERATOR),
        ),
    )
    ssh_operate = Phase(
        "ssh_operate",
        "SSH环境操作",
        tuple(
            ProviderActionStep(action, state, provider)
            for action in provider.actions(DvPhase.SSH_OPERATE)
        ),
    )
    return Plan(
        "dv.initialize.v1",
        "1",
        (precheck, power_cycle, serial_prepare, wait_ssh, ssh_operate),
    )
