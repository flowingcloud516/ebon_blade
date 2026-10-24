"""Validated, GUI-independent workspace data."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any

KINDS = {"EVB": "EVB", "DV": "DV", "SERVER": "通用服务器"}
TEST_TYPES = {"test_type_1": "测试类型 1"}
SCHEMA_VERSION = 2


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
class TargetSelection:
    """One environment slot used by the current test plan.

    Multiple slots can use the same kind. environment_id may be empty while the
    user is still editing the plan, but a run requires every slot to resolve.
    """

    id: str
    kind: str = "EVB"
    environment_id: str = ""

    def validate(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"target-[A-Za-z0-9_-]{1,56}", self.id):
            raise ValidationError("环境槽位编号格式错误")
        if self.kind not in KINDS:
            raise ValidationError("环境槽位使用了不支持的类型")
        if not isinstance(self.environment_id, str):
            raise ValidationError("环境槽位引用必须是文本")

    @classmethod
    def from_dict(cls, value: Any) -> TargetSelection:
        data = object_fields(value, set(cls.__dataclass_fields__), "环境槽位")
        try:
            target = cls(**data)
        except TypeError as exc:
            raise ValidationError("环境槽位缺少必要字段") from exc
        target.validate()
        return target


@dataclass
class WorkspaceData:
    schema_version: int = SCHEMA_VERSION
    name: str = "我的工作空间"
    environments: list[Environment] = field(default_factory=list)
    test_type: str = "test_type_1"
    targets: list[TargetSelection] = field(
        default_factory=lambda: [TargetSelection("target-1")]
    )
    settings: dict[str, str] = field(default_factory=lambda: {
        "firmware_root": "", "ftp_root": "", "launcher_path": "", "python_path": ""
    })

    def validate(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValidationError("工作空间格式不受当前版本支持，请勿覆盖原文件")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("工作空间名称不能为空")
        if self.test_type not in TEST_TYPES:
            raise ValidationError("当前版本不支持此测试类型")
        ids = set()
        for env in self.environments:
            env.validate()
            if env.id.casefold() in ids:
                raise ValidationError(f"环境编号重复：{env.id}")
            ids.add(env.id.casefold())
        if not isinstance(self.targets, list):
            raise ValidationError("本次环境组合格式错误")
        target_ids: set[str] = set()
        selected_environments: set[str] = set()
        for target in self.targets:
            target.validate()
            if target.id in target_ids:
                raise ValidationError(f"环境槽位编号重复：{target.id}")
            target_ids.add(target.id)
            if target.environment_id:
                env = next((e for e in self.environments if e.id == target.environment_id), None)
                if env is None or env.kind != target.kind:
                    raise ValidationError("环境槽位引用了不存在或类型不符的档案")
                if target.environment_id.casefold() in selected_environments:
                    raise ValidationError(f"同一个环境不能在本次组合中重复使用：{target.environment_id}")
                selected_environments.add(target.environment_id.casefold())
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
        if not isinstance(value, dict):
            raise ValidationError("工作空间必须是 JSON 对象")
        data = cls._migrate_v1(value) if value.get("schema_version") == 1 else value
        data = object_fields(data, set(cls.__dataclass_fields__), "工作空间")
        if "schema_version" not in data:
            raise ValidationError("缺少工作空间格式版本")
        data = dict(data)
        if not isinstance(data.get("environments", []), list):
            raise ValidationError("环境列表格式错误")
        data["environments"] = [Environment.from_dict(e) for e in data.get("environments", [])]
        if not isinstance(data.get("targets", []), list):
            raise ValidationError("本次环境组合格式错误")
        data["targets"] = [TargetSelection.from_dict(t) for t in data.get("targets", [])]
        try:
            workspace = cls(**data)
            workspace.validate()
        except (TypeError, KeyError) as exc:
            raise ValidationError("工作空间字段格式错误") from exc
        return workspace

    @staticmethod
    def _migrate_v1(value: dict) -> dict:
        allowed = {"schema_version", "name", "environments", "selections", "active_kind", "settings"}
        object_fields(value, allowed, "旧版工作空间")
        selections = value.get("selections", {})
        if not isinstance(selections, dict):
            raise ValidationError("旧版环境选择格式错误")
        targets = []
        for index, kind in enumerate(KINDS, start=1):
            env_id = selections.get(kind, "")
            if env_id:
                targets.append({"id": f"target-{index}", "kind": kind, "environment_id": env_id})
        if not targets:
            active = value.get("active_kind", "EVB")
            targets = [{"id": "target-1", "kind": active if active in KINDS else "EVB", "environment_id": ""}]
        return {
            "schema_version": SCHEMA_VERSION,
            "name": value.get("name", "我的工作空间"),
            "environments": value.get("environments", []),
            "test_type": "test_type_1",
            "targets": targets,
            "settings": value.get("settings", {}),
        }

    def environment(self, env_id: str) -> Environment | None:
        return next((e for e in self.environments if e.id == env_id), None)

    def resolved_targets(self) -> list[Environment]:
        if not self.targets:
            raise ValidationError("请至少添加一个环境")
        result = []
        for index, target in enumerate(self.targets, start=1):
            if not target.environment_id:
                raise ValidationError(f"第 {index} 个环境尚未选择具体档案")
            env = self.environment(target.environment_id)
            if env is None or env.kind != target.kind:
                raise ValidationError(f"第 {index} 个环境档案不存在或类型不符")
            result.append(env)
        return result

    def next_target_id(self) -> str:
        number = 1
        existing = {target.id for target in self.targets}
        while f"target-{number}" in existing:
            number += 1
        return f"target-{number}"

    def add_target(self, kind: str = "EVB") -> TargetSelection:
        target = TargetSelection(self.next_target_id(), kind)
        self.targets.append(target)
        self.validate()
        return target

    def target(self, target_id: str) -> TargetSelection:
        target = next((t for t in self.targets if t.id == target_id), None)
        if target is None:
            raise ValidationError("环境槽位不存在")
        return target

    def remove_target(self, target_id: str) -> None:
        self.targets = [target for target in self.targets if target.id != target_id]
        self.validate()

    def set_target_kind(self, target_id: str, kind: str) -> None:
        if kind not in KINDS:
            raise ValidationError("不支持的环境类型")
        target = self.target(target_id)
        target.kind = kind
        target.environment_id = ""
        self.validate()

    def set_target_environment(self, target_id: str, env_id: str) -> None:
        target = self.target(target_id)
        target.environment_id = env_id
        self.validate()

    def upsert(self, env: Environment, original_id: str | None = None) -> None:
        env.validate()
        if any(e.id.casefold() == env.id.casefold() and e.id != original_id for e in self.environments):
            raise ValidationError(f"环境编号已存在：{env.id}")
        self.environments = [e for e in self.environments if e.id != original_id] + [env]
        for target in self.targets:
            if target.environment_id == original_id:
                target.environment_id = env.id
                target.kind = env.kind
        self.validate()
