"""Atomic local persistence; no network calls or device actions on opening a workspace."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .models import ValidationError, WorkspaceData


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValidationError(f"无法读取 JSON 文件，原文件未修改：{path.name}") from exc


def atomic_json(path: Path, data) -> None:
    # Serialize before creating any temporary file; NaN is not valid workspace JSON.
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".save-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class WorkspaceStore:
    def __init__(self, root: Path, data: WorkspaceData, digest: str):
        self.root = root.resolve()
        self.data = data
        self._digest = digest

    @property
    def path(self) -> Path:
        return self.root / "workspace.json"

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def open(cls, root: Path) -> WorkspaceStore:
        root = root.resolve()
        path = root / "workspace.json"
        if not path.is_file():
            raise ValidationError("此目录没有 workspace.json，请使用“新建”创建工作空间")
        # Read once so the digest corresponds to the data we actually parsed.
        raw = path.read_bytes()
        try:
            data = WorkspaceData.from_dict(json.loads(raw.decode("utf-8-sig")))
        except (ValueError, UnicodeError) as exc:
            raise ValidationError(f"工作空间无法打开，原文件保持不变：{exc}") from exc
        return cls(root, data, hashlib.sha256(raw).hexdigest())

    @classmethod
    def create(cls, root: Path) -> WorkspaceStore:
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = root / "workspace.json"
        if path.exists():
            raise ValidationError("此目录已有工作空间，请使用“打开”")
        # Exclusive creation prevents two clients from overwriting each other's new workspace.
        data = WorkspaceData(name=root.name or "工作空间")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(data.to_dict(), stream, ensure_ascii=False, indent=2)
        return cls.open(root)

    def save(self, data: WorkspaceData) -> None:
        data.validate()
        # One local writer at a time, and optimistic conflict detection across windows.
        lock = self.root / ".save.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ValidationError("工作空间正在保存；若进程异常退出，请检查 .save.lock") from exc
        try:
            os.close(fd)
            if not self.path.exists() or self.digest(self.path) != self._digest:
                raise ValidationError("配置已被其他窗口或程序修改，请重新打开工作空间后再编辑")
            atomic_json(self.path, data.to_dict())
            self._digest = self.digest(self.path)
            self.data = data
        finally:
            lock.unlink(missing_ok=True)


def redact(value):
    """Best effort for diagnostic snapshots; workspace config must use credential references."""
    if isinstance(value, dict):
        return {
            key: "<redacted>" if any(word in key.lower() for word in
                ("password", "passwd", "secret", "token", "private_key")) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
