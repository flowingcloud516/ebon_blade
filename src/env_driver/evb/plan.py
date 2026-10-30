"""Fixed public phase and step ordering for EVB initialization."""
from __future__ import annotations

from ..core.plan import Phase, Plan
from .artifacts import ArtifactPreparationCoordinator
from .contract import EvbContributionProvider
from .filezilla import EvbWorkspaceMaterializer
from .steps import (
    AcquireFileZillaLeaseStep,
    ClearFileZillaRootStep,
    CompleteStartupStep,
    EnsureArtifactsStep,
    ExtractBootScriptStep,
    ExtractFirmwareStep,
    PrepareWorkspaceArtifactsStep,
    ProviderActionStep,
    ReleaseFileZillaLeaseStep,
    RequireBundleStep,
    ResolveArtifactsStep,
    UploadPackageStep,
    ValidateFileZillaRootStep,
    WaitForEvbSshStep,
)
from .types import EvbExecutionState, EvbPhase


def build_evb_initialize_plan(
    state: EvbExecutionState,
    provider: EvbContributionProvider,
    *,
    artifacts: ArtifactPreparationCoordinator,
    materializer: EvbWorkspaceMaterializer,
) -> Plan:
    """Build the public four-phase plan around provider-contributed actions."""

    configure_provider_steps = tuple(
        ProviderActionStep(item, state, provider)
        for item in provider.actions(EvbPhase.CONFIGURE)
    )
    start_provider_steps = tuple(
        ProviderActionStep(item, state, provider)
        for item in provider.actions(EvbPhase.START)
    )
    operate_provider_steps = tuple(
        ProviderActionStep(item, state, provider)
        for item in provider.actions(EvbPhase.OPERATE)
    )
    deployment = provider.deployment_layout(state.request)

    material = Phase(
        "material",
        "备料",
        (
            ResolveArtifactsStep(state),
            EnsureArtifactsStep(state, artifacts, provider),
            RequireBundleStep(state),
        ),
    )
    configure = Phase(
        "configure",
        "配置",
        (
            AcquireFileZillaLeaseStep(state),
            ValidateFileZillaRootStep(state),
            ClearFileZillaRootStep(state),
            ExtractFirmwareStep(state),
            PrepareWorkspaceArtifactsStep(state, materializer, provider),
            ExtractBootScriptStep(state, materializer),
            *configure_provider_steps,
        ),
    )
    start = Phase(
        "start",
        "启动",
        (
            *start_provider_steps,
            CompleteStartupStep(state, start_provider_steps),
            ReleaseFileZillaLeaseStep(state),
        ),
    )
    operate = Phase(
        "operate",
        "环境上操作",
        (
            WaitForEvbSshStep(state),
            UploadPackageStep(
                "3.3.packages.upload_driver",
                "上传驱动包",
                "driver",
                deployment.driver_remote_path,
                state,
            ),
            UploadPackageStep(
                "3.4.packages.upload_third_party",
                "上传三方包",
                "third_party",
                deployment.third_party_remote_path,
                state,
            ),
            *operate_provider_steps,
        ),
    )
    return Plan("evb.initialize.v1", "1", (material, configure, start, operate))
