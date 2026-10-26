from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .errors import HostKeyError
from .models import HostKeyPolicy, HostKeySettings


class HostKeyStore:
    """Project-local environment-id to host-key fingerprint mapping."""

    def __init__(self, settings: HostKeySettings):
        self.settings = settings
        self._rotation_consumed = False

    def _read(self) -> dict[str, str]:
        path = self.settings.store_path
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise HostKeyError("host key store cannot be read") from exc
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise HostKeyError("host key store has an invalid format")
        return value

    def _write(self, value: dict[str, str]) -> None:
        path = self.settings.store_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".host-keys-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def verify(self, fingerprint: str) -> bool:
        policy = self.settings.policy
        if policy is HostKeyPolicy.INSECURE_ACCEPT_ANY:
            return True
        records = self._read()
        current = records.get(self.settings.environment_id)
        if current == fingerprint:
            return True
        if current is None:
            if policy is HostKeyPolicy.STRICT:
                raise HostKeyError("SSH host key has not been provisioned for this environment")
            records[self.settings.environment_id] = fingerprint
            self._write(records)
            return True
        if (policy is HostKeyPolicy.RESET_FOR_REPROVISION
                and self.settings.rotation_authorized and not self._rotation_consumed):
            records[self.settings.environment_id] = fingerprint
            self._write(records)
            self._rotation_consumed = True
            return True
        raise HostKeyError("SSH host key does not match the environment record")
