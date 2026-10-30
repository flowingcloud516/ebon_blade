from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
from typing import Protocol, runtime_checkable

from .errors import BmcUnsupportedActionError
from .models import (
    BiosSnapshot,
    IssuePolicy,
    PowerAction,
    PowerActionReceipt,
    PowerOperationResult,
    PowerOperationStatus,
    PowerState,
)


@runtime_checkable
class BmcBackend(Protocol):
    @property
    def backend_name(self) -> str: ...

    async def get_power_state(self) -> PowerState: ...

    async def issue_power_action(self, action: PowerAction) -> PowerActionReceipt: ...

    async def read_all_bios_config(self) -> BiosSnapshot: ...


class BmcConnector:
    """Backend-neutral BMC power semantics with evidence-based completion."""

    def __init__(
        self,
        backend: BmcBackend,
        *,
        transition_timeout: float = 120.0,
        poll_interval: float = 2.0,
    ) -> None:
        if not isinstance(backend, BmcBackend):
            raise TypeError("backend must implement BmcBackend")
        if transition_timeout <= 0 or poll_interval < 0:
            raise ValueError("BMC transition timeout must be positive and polling non-negative")
        self.backend = backend
        self.transition_timeout = transition_timeout
        self.poll_interval = poll_interval
        self._closed = False

    async def get_power_state(self) -> PowerState:
        self._ensure_open()
        state = await self.backend.get_power_state()
        if not isinstance(state, PowerState):
            raise TypeError("BMC backend get_power_state() must return PowerState")
        return state

    async def power_on(
        self,
        *,
        issue_policy: IssuePolicy = IssuePolicy.IF_NEEDED,
    ) -> PowerOperationResult:
        return await self._operate(PowerAction.POWER_ON, PowerState.ON, issue_policy)

    async def force_off(
        self,
        *,
        issue_policy: IssuePolicy = IssuePolicy.IF_NEEDED,
    ) -> PowerOperationResult:
        return await self._operate(PowerAction.FORCE_OFF, PowerState.OFF, issue_policy)

    async def read_all_bios_config(self) -> BiosSnapshot:
        self._ensure_open()
        snapshot = await self.backend.read_all_bios_config()
        if not isinstance(snapshot, BiosSnapshot):
            raise TypeError("BMC backend read_all_bios_config() must return BiosSnapshot")
        return snapshot

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self.backend, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result

    async def _operate(
        self,
        action: PowerAction,
        target: PowerState,
        issue_policy: IssuePolicy,
    ) -> PowerOperationResult:
        self._ensure_open()
        if not isinstance(issue_policy, IssuePolicy):
            raise TypeError("issue_policy must be IssuePolicy")
        started = datetime.now(timezone.utc)
        previous = await self.get_power_state()
        if previous is target and issue_policy is IssuePolicy.IF_NEEDED:
            return self._result(
                action,
                previous,
                previous,
                PowerOperationStatus.SUCCEEDED,
                action_issued=False,
                action_accepted=None,
                verified=True,
                changed=False,
                summary="target power state already satisfied",
                started=started,
            )

        try:
            receipt = await self.backend.issue_power_action(action)
        except BmcUnsupportedActionError as exc:
            return self._result(
                action,
                previous,
                previous,
                PowerOperationStatus.UNSUPPORTED,
                action_issued=False,
                action_accepted=False,
                verified=False,
                changed=False,
                summary=str(exc) or "BMC action is unsupported",
                started=started,
            )
        except Exception as exc:
            return self._result(
                action,
                previous,
                PowerState.UNKNOWN,
                PowerOperationStatus.UNKNOWN,
                action_issued=True,
                action_accepted=None,
                verified=False,
                changed=False,
                summary=f"BMC action result is unknown: {type(exc).__name__}",
                started=started,
            )
        if not isinstance(receipt, PowerActionReceipt):
            raise TypeError("BMC backend issue_power_action() must return PowerActionReceipt")
        if not receipt.accepted:
            return self._result(
                action,
                previous,
                previous,
                PowerOperationStatus.FAILED,
                action_issued=True,
                action_accepted=False,
                verified=False,
                changed=False,
                summary=receipt.diagnostic_summary or "BMC rejected the requested action",
                started=started,
            )

        deadline = asyncio.get_running_loop().time() + self.transition_timeout
        final = PowerState.UNKNOWN
        last_error: Exception | None = None
        while True:
            try:
                final = await self.get_power_state()
                last_error = None
                if final is target:
                    return self._result(
                        action,
                        previous,
                        final,
                        PowerOperationStatus.SUCCEEDED,
                        action_issued=True,
                        action_accepted=True,
                        verified=True,
                        changed=previous is not final,
                        summary=receipt.diagnostic_summary or "target power state verified",
                        started=started,
                    )
            except Exception as exc:
                last_error = exc
            now = asyncio.get_running_loop().time()
            if now >= deadline:
                break
            await asyncio.sleep(min(self.poll_interval, deadline - now))

        if last_error is not None:
            summary = f"power action accepted but final state is unknown: {type(last_error).__name__}"
            status = PowerOperationStatus.UNKNOWN
        else:
            summary = f"power state did not reach {target.value} before timeout"
            status = PowerOperationStatus.FAILED
        return self._result(
            action,
            previous,
            final,
            status,
            action_issued=True,
            action_accepted=True,
            verified=False,
            changed=previous is not final and final is not PowerState.UNKNOWN,
            summary=summary,
            started=started,
        )

    def _result(
        self,
        action: PowerAction,
        previous: PowerState,
        final: PowerState,
        status: PowerOperationStatus,
        *,
        action_issued: bool,
        action_accepted: bool | None,
        verified: bool,
        changed: bool,
        summary: str,
        started: datetime,
    ) -> PowerOperationResult:
        return PowerOperationResult(
            action,
            previous,
            final,
            status,
            self.backend.backend_name,
            action_issued,
            action_accepted,
            verified,
            changed,
            summary,
            started,
            datetime.now(timezone.utc),
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("BMC connector is closed")
