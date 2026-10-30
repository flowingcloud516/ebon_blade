"""Workspace-local version cache with an explicitly injected remote source."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Protocol, runtime_checkable


_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _component(value: str, label: str) -> str:
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


@runtime_checkable
class VersionRemote(Protocol):
    """Implemented by trusted transport glue, normally SSH/SFTP."""

    async def list_directories(self, remote_path: str) -> tuple[str, ...]: ...

    async def download_tree(self, remote_path: str, local_path: Path) -> None: ...


@dataclass(frozen=True)
class PreparedVersion:
    path: Path
    reused_in_run: bool = False


class SimpleVersionStore:
    """The minimal `platform/version` store agreed for the first release."""

    def __init__(self, workspace_root: Path, remote_root: str, remote: VersionRemote) -> None:
        self.workspace_root = workspace_root.resolve()
        self.cache_root = self.workspace_root / "versions"
        root = PurePosixPath(remote_root)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("remote version root must be an absolute safe POSIX path")
        self.remote_root = root
        self.remote = remote

    async def list_platforms(self) -> tuple[str, ...]:
        return self._safe_entries(await self.remote.list_directories(str(self.remote_root)))

    async def list_versions(self, platform: str) -> tuple[str, ...]:
        platform = _component(platform, "platform")
        return self._safe_entries(
            await self.remote.list_directories(str(self.remote_root / platform))
        )

    async def ensure_local(self, platform: str, version: str) -> Path:
        platform = _component(platform, "platform")
        version = _component(version, "version")
        destination = self.cache_root / platform / version
        if destination.is_dir():
            return destination
        if destination.exists():
            raise NotADirectoryError(destination)

        staging = destination.with_name(destination.name + ".downloading")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink()
        remote_path = str(self.remote_root / platform / version)
        try:
            await self.remote.download_tree(remote_path, staging)
            if not staging.is_dir():
                raise RuntimeError("remote download did not create a version directory")
            staging.replace(destination)
        except BaseException:
            if staging.exists():
                if staging.is_dir() and not staging.is_symlink():
                    shutil.rmtree(staging)
                else:
                    staging.unlink()
            raise
        return destination

    @staticmethod
    def _safe_entries(entries) -> tuple[str, ...]:
        result = []
        for entry in entries:
            result.append(_component(entry, "remote directory entry"))
        return tuple(sorted(set(result)))


class ArtifactPreparationCoordinator:
    """Deduplicates one version preparation across all EVBs in a run."""

    def __init__(self, store: SimpleVersionStore) -> None:
        self.store = store
        self._tasks: dict[tuple[str, str], asyncio.Task[Path]] = {}
        self._completed: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def prepare(self, platform: str, version: str) -> PreparedVersion:
        key = (_component(platform, "platform"), _component(version, "version"))
        async with self._lock:
            reused = key in self._tasks or key in self._completed
            task = self._tasks.get(key)
            if task is None:
                task = asyncio.create_task(self.store.ensure_local(*key))
                self._tasks[key] = task
        try:
            path = await asyncio.shield(task)
        except BaseException:
            async with self._lock:
                if self._tasks.get(key) is task and task.done():
                    self._tasks.pop(key, None)
            raise
        async with self._lock:
            self._completed.add(key)
        return PreparedVersion(path, reused)


class SftpVersionRemote:
    """Thin adapter around a factory returning a managed SSH session."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def list_directories(self, remote_path: str) -> tuple[str, ...]:
        session = self._session_factory()
        try:
            return await session.listdir(remote_path, directories_only=True)
        finally:
            await session.close()

    async def download_tree(self, remote_path: str, local_path: Path) -> None:
        session = self._session_factory()
        try:
            await session.download_tree(remote_path, local_path)
        finally:
            await session.close()
