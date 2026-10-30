"""Safe preparation of the fixed local FileZilla root and workspace artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


_MARKER = ".ebon-filezilla-root"
_RESERVED_WORKSPACE_NAMES = {"workspace.json", "versions", "runs", ".run.lock", ".locks"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_target(value: str, label: str) -> Path:
    posix = PurePosixPath(value)
    if not value or posix.is_absolute() or ".." in posix.parts or posix.parts[0] in {"", "."}:
        raise ValueError(f"unsafe {label}: {value!r}")
    path = Path(*posix.parts)
    if path.parts[0].casefold() in {item.casefold() for item in _RESERVED_WORKSPACE_NAMES}:
        raise ValueError(f"{label} targets a reserved workspace path: {value!r}")
    return path


def _safe_zip_members(archive: zipfile.ZipFile):
    for info in archive.infolist():
        value = info.filename.replace("\\", "/")
        path = PurePosixPath(value)
        mode = info.external_attr >> 16
        if (
            not value
            or path.is_absolute()
            or (len(value) >= 2 and value[0].isalpha() and value[1] == ":")
            or ".." in path.parts
            or (mode and stat.S_ISLNK(mode))
        ):
            raise ValueError(f"unsafe ZIP member: {info.filename!r}")
        yield info


@dataclass(frozen=True)
class WorkspaceArtifactLayout:
    boot_archive: str
    boot_directory: str
    driver_archive: str
    third_party_archive: str

    def resolved(self, workspace_root: Path) -> "ResolvedWorkspaceArtifactLayout":
        root = workspace_root.resolve()
        resolved = ResolvedWorkspaceArtifactLayout(
            root / _relative_target(self.boot_archive, "boot archive"),
            root / _relative_target(self.boot_directory, "boot directory"),
            root / _relative_target(self.driver_archive, "driver archive"),
            root / _relative_target(self.third_party_archive, "third-party archive"),
        )
        archives = (
            resolved.boot_archive,
            resolved.driver_archive,
            resolved.third_party_archive,
        )
        normalized = [str(item).casefold() for item in archives]
        if len(set(normalized)) != len(normalized):
            raise ValueError("workspace artifact targets must be distinct")
        if any(_inside(item, resolved.boot_directory) for item in archives):
            raise ValueError("boot extraction directory must not contain an archive target")
        return resolved


@dataclass(frozen=True)
class ResolvedWorkspaceArtifactLayout:
    boot_archive: Path
    boot_directory: Path
    driver_archive: Path
    third_party_archive: Path


class FileZillaRootLease:
    def __init__(self, lock_path: Path, handle: int, root: Path) -> None:
        self.lock_path = lock_path
        self._handle = handle
        self.root = root
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        os.close(self._handle)
        self.lock_path.unlink(missing_ok=True)


class FileZillaRootManager:
    def __init__(self, workspace_root: Path, root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.root = root.resolve()
        digest = hashlib.sha256(str(self.root).casefold().encode("utf-8")).hexdigest()[:24]
        lock_root = Path(tempfile.gettempdir()) / "ebon-blade-locks"
        self.lock_path = lock_root / f"filezilla-{digest}.lock"

    def adopt(self) -> None:
        """Explicit one-time ownership marker; callers must obtain user intent first."""
        self._validate_location(require_marker=False)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / _MARKER).write_text("managed by ebon-blade\n", encoding="utf-8")

    def acquire(self) -> FileZillaRootLease:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("FileZilla root is already leased by another task") from exc
        os.write(handle, f"pid={os.getpid()}\nroot={self.root}\n".encode("utf-8"))
        return FileZillaRootLease(self.lock_path, handle, self.root)

    def validate(self) -> None:
        self._validate_location(require_marker=True)

    def clear(self, lease: FileZillaRootLease) -> None:
        self._require_lease(lease)
        self.validate()
        for child in self.root.iterdir():
            if child.name == _MARKER:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def extract_firmware(self, archive_path: Path, lease: FileZillaRootLease) -> None:
        self._require_lease(lease)
        self.validate()
        archive_path = archive_path.resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            members = tuple(_safe_zip_members(archive))
            archive.extractall(self.root, members=members)
        # The normal path extracts directly from the workspace cache, so no archive is
        # copied into the served root. If a plugin supplied a temporary archive inside
        # the root, remove only that exact archive, never ZIP payloads from the firmware.
        if _inside(archive_path, self.root):
            archive_path.unlink(missing_ok=True)

    def _validate_location(self, *, require_marker: bool) -> None:
        root = self.root
        workspace = self.workspace_root
        if root == Path(root.anchor):
            raise ValueError("FileZilla root must not be a drive root")
        if root == workspace or _inside(root, workspace) or _inside(workspace, root):
            raise ValueError("FileZilla root must be separate from the workspace")
        home = Path.home().resolve()
        if root == home:
            raise ValueError("FileZilla root must not be the user home directory")
        windows = os.environ.get("WINDIR")
        if windows and _inside(root, Path(windows).resolve()):
            raise ValueError("FileZilla root must not be inside the Windows directory")
        if require_marker:
            if not root.is_dir():
                raise FileNotFoundError(root)
            if not (root / _MARKER).is_file():
                raise ValueError("FileZilla root has not been explicitly adopted")

    def _require_lease(self, lease: FileZillaRootLease) -> None:
        if lease.root != self.root or lease.released:
            raise RuntimeError("an active lease for this FileZilla root is required")


class EvbWorkspaceMaterializer:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def copy_archives(
        self,
        *,
        boot_archive: Path,
        driver_archive: Path,
        third_party_archive: Path,
        layout: WorkspaceArtifactLayout,
    ) -> ResolvedWorkspaceArtifactLayout:
        target = layout.resolved(self.workspace_root)
        for source, destination in (
            (boot_archive, target.boot_archive),
            (driver_archive, target.driver_archive),
            (third_party_archive, target.third_party_archive),
        ):
            self._atomic_copy(source, destination)
        return target

    def extract_boot_script(self, archive_path: Path, destination: Path) -> None:
        destination = destination.resolve()
        if not _inside(destination, self.workspace_root) or destination == self.workspace_root:
            raise ValueError("boot directory must be a managed workspace child")
        temporary = destination.with_name(destination.name + ".ebon-extract")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = tuple(_safe_zip_members(archive))
                archive.extractall(temporary, members=members)
            if destination.exists():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            temporary.replace(destination)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        source = source.resolve()
        destination = destination.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if not _inside(destination, self.workspace_root) or destination == self.workspace_root:
            raise ValueError("artifact target must be inside the workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".ebon-copy")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
