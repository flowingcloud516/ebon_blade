"""Reusable public EVB steps; private behavior stays behind a contribution provider."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

from ..core.steps import CheckStep, OperationStep
from ..core.types import SideEffect, StepResult, StepStatus
from .contract import EvbContributionProvider
from .types import (
    EvbActionContext,
    EvbActionDefinition,
    EvbArtifactBundle,
    EvbExecutionState,
    EvbPhase,
)
from .artifacts import ArtifactPreparationCoordinator
from .filezilla import EvbWorkspaceMaterializer, FileZillaRootManager


def _bundle(state: EvbExecutionState) -> EvbArtifactBundle:
    if state.bundle is None:
        raise RuntimeError("EVB artifacts have not been prepared")
    return state.bundle


class ResolveArtifactsStep(CheckStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__("0.1.artifacts.resolve", "解析EVB平台与版本", timeout=5)
        self.state = state

    async def check(self, context) -> StepResult:
        request = self.state.request
        if not request.platform.strip() or not request.version.strip():
            return StepResult(StepStatus.FAILED, "EVB platform/version is missing")
        return StepResult.success(
            f"resolved {request.platform}/{request.version}",
            details={"platform": request.platform, "version": request.version},
        )


class EnsureArtifactsStep(OperationStep):
    def __init__(
        self,
        state: EvbExecutionState,
        coordinator: ArtifactPreparationCoordinator,
        provider: EvbContributionProvider,
    ) -> None:
        super().__init__(
            "0.2.artifacts.ensure_local",
            "准备本地版本缓存",
            timeout=600,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state
        self.coordinator = coordinator
        self.provider = provider

    async def perform(self, context) -> StepResult:
        request = self.state.request
        prepared = await self.coordinator.prepare(request.platform, request.version)
        layout = self.provider.artifact_layout(request)
        root = prepared.path
        self.state.bundle = EvbArtifactBundle(
            root=root,
            firmware=root / Path(*layout.firmware.split("/")),
            boot_script=root / Path(*layout.boot_script.split("/")),
            driver=root / Path(*layout.driver.split("/")),
            third_party=root / Path(*layout.third_party.split("/")),
            reused_in_run=prepared.reused_in_run,
        )
        if prepared.reused_in_run:
            return StepResult(
                StepStatus.SKIPPED,
                "reused version already prepared in this run",
                details={"path": str(root)},
            )
        return StepResult.success("version is available in the workspace cache", details={"path": str(root)})


class RequireBundleStep(CheckStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__("0.3.artifacts.require_bundle", "检查四类版本制品", timeout=10)
        self.state = state

    async def check(self, context) -> StepResult:
        bundle = _bundle(self.state)
        missing = [
            name
            for name, path in (
                ("firmware", bundle.firmware),
                ("boot_script", bundle.boot_script),
                ("driver", bundle.driver),
                ("third_party", bundle.third_party),
            )
            if not path.is_file()
        ]
        if missing:
            return StepResult(
                StepStatus.FAILED,
                "required EVB artifacts are missing: " + ", ".join(missing),
            )
        return StepResult.success("all four EVB artifacts are present")


class AcquireFileZillaLeaseStep(OperationStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__(
            "1.1.filezilla.acquire_lease",
            "锁定FileZilla固件目录",
            timeout=30,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state

    async def perform(self, context) -> StepResult:
        manager = FileZillaRootManager(
            self.state.request.workspace_root,
            self.state.request.filezilla_root,
        )
        self.state.filezilla_manager = manager
        self.state.filezilla_lease = manager.acquire()
        return StepResult.success("FileZilla root lease acquired")


class ValidateFileZillaRootStep(CheckStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__("1.2.filezilla.validate_root", "检查FileZilla目录安全性", timeout=5)
        self.state = state

    async def check(self, context) -> StepResult:
        if self.state.filezilla_manager is None:
            return StepResult(StepStatus.FAILED, "FileZilla manager is unavailable")
        self.state.filezilla_manager.validate()
        return StepResult.success("FileZilla root passed safety validation")


class ClearFileZillaRootStep(OperationStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__(
            "1.3.filezilla.clear_root",
            "清空FileZilla旧固件",
            timeout=300,
            side_effect=SideEffect.DESTRUCTIVE,
        )
        self.state = state

    async def perform(self, context) -> StepResult:
        self.state.filezilla_manager.clear(self.state.filezilla_lease)
        return StepResult.success("FileZilla root cleared", changed=True)


class ExtractFirmwareStep(OperationStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__(
            "1.4.firmware.extract",
            "解压固件到FileZilla目录",
            timeout=300,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state

    async def perform(self, context) -> StepResult:
        bundle = _bundle(self.state)
        self.state.filezilla_manager.extract_firmware(bundle.firmware, self.state.filezilla_lease)
        return StepResult.success("firmware extracted for FileZilla", changed=True)


class PrepareWorkspaceArtifactsStep(OperationStep):
    def __init__(
        self,
        state: EvbExecutionState,
        materializer: EvbWorkspaceMaterializer,
        provider: EvbContributionProvider,
    ) -> None:
        super().__init__(
            "1.5.workspace.prepare_artifacts",
            "准备启动脚本、驱动和三方包",
            timeout=300,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state
        self.materializer = materializer
        self.provider = provider

    async def perform(self, context) -> StepResult:
        bundle = _bundle(self.state)
        layout = self.provider.workspace_layout(self.state.request)
        self.state.workspace_layout = self.materializer.copy_archives(
            boot_archive=bundle.boot_script,
            driver_archive=bundle.driver,
            third_party_archive=bundle.third_party,
            layout=layout,
        )
        return StepResult.success("workspace artifacts prepared", changed=True)


class ExtractBootScriptStep(OperationStep):
    def __init__(self, state: EvbExecutionState, materializer: EvbWorkspaceMaterializer) -> None:
        super().__init__(
            "1.6.startup.extract",
            "解压EVB启动脚本",
            timeout=120,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state
        self.materializer = materializer

    async def perform(self, context) -> StepResult:
        layout = self.state.workspace_layout
        if layout is None:
            raise RuntimeError("workspace artifacts are unavailable")
        self.materializer.extract_boot_script(layout.boot_archive, layout.boot_directory)
        return StepResult.success("startup source extracted", changed=True)


class ProviderActionStep(OperationStep):
    def __init__(
        self,
        definition: EvbActionDefinition,
        state: EvbExecutionState,
        provider: EvbContributionProvider,
    ) -> None:
        super().__init__(
            f"provider.{definition.phase.value}.{definition.action_id}",
            definition.title,
            timeout=definition.timeout,
            side_effect=definition.side_effect,
        )
        self.definition = definition
        self.state = state
        self.provider = provider

    async def perform(self, context) -> StepResult:
        bundle = _bundle(self.state)
        if self.definition.phase is EvbPhase.START:
            self.state.start_action_started = True
        result = await self.provider.execute_action(
            self.definition.action_id,
            EvbActionContext(
                self.state.request,
                bundle,
                context,
                self.state.workspace_layout,
            ),
        )
        if not isinstance(result, StepResult):
            raise TypeError("EVB provider execute_action() must return StepResult")
        return result


class CompleteStartupStep(CheckStep):
    def __init__(self, state: EvbExecutionState, start_steps: Iterable[ProviderActionStep]) -> None:
        super().__init__(
            "2.last.startup.confirm_complete",
            "复核EVB启动完成",
            timeout=30,
        )
        self.state = state
        self.start_step_ids = tuple(step.step_id for step in start_steps)

    async def check(self, context) -> StepResult:
        missing = [
            step_id
            for step_id in self.start_step_ids
            if context.step_results.get(step_id) is None
            or context.step_results[step_id].status not in {StepStatus.SUCCEEDED, StepStatus.SKIPPED}
        ]
        if missing:
            return StepResult(StepStatus.FAILED, "startup evidence is incomplete")
        self.state.start_phase_completed = True
        return StepResult.success("startup actions completed with current-run evidence")


class ReleaseFileZillaLeaseStep(OperationStep):
    def __init__(self, state: EvbExecutionState) -> None:
        super().__init__(
            "2.release.filezilla_lease",
            "释放FileZilla固件目录锁",
            timeout=5,
            side_effect=SideEffect.IDEMPOTENT,
        )
        self.state = state

    async def perform(self, context) -> StepResult:
        if self.state.filezilla_lease is not None:
            self.state.filezilla_lease.release()
        return StepResult.success("FileZilla root lease released")


class WaitForEvbSshStep(CheckStep):
    def __init__(self, state: EvbExecutionState, *, poll_interval: float = 10.0) -> None:
        super().__init__("3.1.evb_ssh.wait_ready", "等待EVB SSH就绪", timeout=1200)
        self.state = state
        self.poll_interval = poll_interval

    async def check(self, context) -> StepResult:
        session = context.resolve_connection(
            self.state.request.ssh_connection_id,
            connector_type="ssh",
        )
        attempts = 0
        while True:
            attempts += 1
            try:
                await session.connect()
            except Exception:
                if context.cancel_event.is_set():
                    raise asyncio.CancelledError
                await asyncio.sleep(self.poll_interval)
                continue
            self.state.log_activation.evb_ssh_ready.set()
            return StepResult.success(
                "EVB SSH connection is ready",
                details={"attempts": attempts},
            )


class UploadPackageStep(OperationStep):
    def __init__(
        self,
        step_id: str,
        title: str,
        source_name: str,
        remote_path: str,
        state: EvbExecutionState,
    ) -> None:
        super().__init__(step_id, title, timeout=600, side_effect=SideEffect.IDEMPOTENT)
        self.source_name = source_name
        self.remote_path = remote_path
        self.state = state

    async def perform(self, context) -> StepResult:
        bundle = _bundle(self.state)
        source = getattr(bundle, self.source_name)
        session = context.resolve_connection(
            self.state.request.ssh_connection_id,
            connector_type="ssh",
        )
        result = await session.upload(source, self.remote_path, atomic=True, overwrite=True)
        if not bool(getattr(result, "verified", False)):
            return StepResult(StepStatus.FAILED, f"{self.source_name} upload size verification failed")
        return StepResult.success(
            f"{self.source_name} uploaded",
            changed=True,
            details={"remote_path": self.remote_path, "bytes": getattr(result, "bytes_transferred", None)},
        )


# Compatibility name for callers built against the initial design draft.
AdapterActionStep = ProviderActionStep
