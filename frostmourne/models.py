"""Validated, GUI-independent workspace data."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any

KINDS = {"EVB": "EVB", "DV": "DV", "SERVER": "通用服务器"}
SCHEMA_VERSION = 1


class ValidationError(ValueError):
    pass


def object_fields(value: Any, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label}必须是 JSON 对象")
    extra = set(value) - allowed
    if extra:
        raise ValidationError(f"{label}包含当前版本不支持的字段：{', '.join(sorted(extra))}")
    return value


@dataclass
class Environment:
    id: str
    kind: str
    name: str
    firmware: str = ""
    bmc_host: str = ""
    bmc_port: int = 22
    expected_mac: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    credential_ref: str = ""
    endpoints: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def validate(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.id):
            raise ValidationError("环境编号应为 1–64 位字母、数字、下划线或短横线")
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ValidationError("不支持的环境类型")
        for key in ("name", "firmware", "bmc_host", "expected_mac", "ssh_host", "credential_ref", "notes"):
            if not isinstance(getattr(self, key), str):
                raise ValidationError(f"{key} 必须是文本")
        if not self.name.strip():
            raise ValidationError("请填写环境名称")
        for port in (self.bmc_port, self.ssh_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValidationError("端口必须在 1–65535 之间")
        if self.expected_mac and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", self.expected_mac):
            raise ValidationError("预期 MAC 请使用完整格式，例如 00:11:22:33:44:55")
        if not isinstance(self.endpoints, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.endpoints.items()
        ):
            raise ValidationError("串口端点必须是名称到地址文本的映射")
        if not isinstance(self.parameters, dict):
            raise ValidationError("扩展参数必须是 JSON 对象")
        try:
            json.dumps(self.parameters, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValidationError("扩展参数必须是有效 JSON，不能包含 NaN 或无穷值") from exc

    @classmethod
    def from_dict(cls, value: Any) -> Environment:
        data = object_fields(value, set(cls.__dataclass_fields__), "环境配置")
        try:
            env = cls(**data)
        except TypeError as exc:
            raise ValidationError("环境配置缺少必要字段") from exc
        env.validate()
        return env


@dataclass
class WorkspaceData:
    schema_version: int = SCHEMA_VERSION
    name: str = "我的工作空间"
    environments: list[Environment] = field(default_factory=list)
    selections: dict[str, str] = field(default_factory=dict)
    active_kind: str = "EVB"
    settings: dict[str, str] = field(default_factory=lambda: {
        "firmware_root": "", "ftp_root": "", "launcher_path": "", "python_path": ""
    })

    def validate(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValidationError("工作空间格式不受当前版本支持，请勿覆盖原文件")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("工作空间名称不能为空")
        if self.active_kind not in KINDS:
            raise ValidationError("无效的当前环境类型")
        ids = set()
        for env in self.environments:
            env.validate()
            if env.id.casefold() in ids:
                raise ValidationError(f"环境编号重复：{env.id}")
            ids.add(env.id.casefold())
        if not isinstance(self.selections, dict):
            raise ValidationError("环境选择格式错误")
        for kind, env_id in self.selections.items():
            if kind not in KINDS or not any(e.id == env_id and e.kind == kind for e in self.environments):
                raise ValidationError("环境选择引用了不存在或类型不符的记录")
        if not isinstance(self.settings, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.settings.items()
        ):
            raise ValidationError("本机设置必须是文本映射")
        allowed = {"firmware_root", "ftp_root", "launcher_path", "python_path"}
        if set(self.settings) - allowed:
            raise ValidationError("存在当前版本不支持的本机设置")

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> WorkspaceData:
        data = object_fields(value, set(cls.__dataclass_fields__), "工作空间")
        if "schema_version" not in data:
            raise ValidationError("缺少工作空间格式版本")
        data = dict(data)
        if not isinstance(data.get("environments", []), list):
            raise ValidationError("环境列表格式错误")
        data["environments"] = [Environment.from_dict(e) for e in data.get("environments", [])]
        try:
            workspace = cls(**data)
            workspace.validate()
        except (TypeError, KeyError) as exc:
            raise ValidationError("工作空间字段格式错误") from exc
        return workspace

    def selected(self, kind: str | None = None) -> Environment | None:
        kind = kind or self.active_kind
        return next((e for e in self.environments if e.kind == kind and e.id == self.selections.get(kind)), None)

    def upsert(self, env: Environment, original_id: str | None = None) -> None:
        env.validate()
        if any(e.id.casefold() == env.id.casefold() and e.id != original_id for e in self.environments):
            raise ValidationError(f"环境编号已存在：{env.id}")
        self.environments = [e for e in self.environments if e.id != original_id] + [env]
        for kind, selected in list(self.selections.items()):
            if selected == original_id:
                del self.selections[kind]
        self.selections[env.kind] = env.id
        self.active_kind = env.kind
        self.validate()
