"""Background-ready execution with durable run records and a strictly offline demo."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from uuid import uuid4
import os

from .adapters import ADAPTERS, Adapter
from .models import Environment, ValidationError
from .storage import atomic_json, redact


def execute_plan(root: Path, environments: list[Environment], settings: dict[str, str],
                 demo: bool, cancel: Event, emit: Callable[[int, str], None],
                 adapters: dict[str, Adapter] | None = None, demo_delay: float = 0.45) -> dict:
    environments = deepcopy(environments)
    if not environments:
        raise ValidationError("请至少选择一个环境")
    for environment in environments:
        environment.validate()
    settings = deepcopy(settings)
    adapters = ADAPTERS if adapters is None else adapters
    lock = root / ".run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValidationError("此工作空间有运行记录锁。请确认没有任务或设备动作仍在执行，再人工处理 .run.lock") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(f"pid={os.getpid()}\n")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    directory = root / "runs" / run_id
    result = {"run_id": run_id, "environment_ids": [e.id for e in environments], "demo": demo,
              "ready": False, "status": "running", "action_state": "not_started",
              "summary": "", "targets": [], "started_at": datetime.now(timezone.utc).isoformat()}
    keep_lock = False

    def report(progress: int, message: str) -> None:
        with (directory / "execution.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        emit(progress, message)

    try:
        directory.mkdir(parents=True)
        from dataclasses import asdict
        atomic_json(directory / "snapshot.json", redact({
            "environments": [asdict(environment) for environment in environments],
            "settings": settings, "demo": demo
        }))
        atomic_json(directory / "result.json", result)
        try:
            if demo:
                report(0, "离线演示：不会连接设备、复制固件或执行任何脚本。")
                steps = [("读取配置快照", None)]
                for environment in environments:
                    steps.extend([
                        (f"模拟检查 {environment.id} / {environment.kind}", environment.id),
                        (f"模拟初始化 {environment.id} / {environment.kind}", environment.id),
                    ])
                steps.append(("保存演示结果", None))
                for index, (step, env_id) in enumerate(steps, start=1):
                    if cancel.wait(demo_delay):
                        result.update(status="cancelled", summary="演示已停止，未操作任何设备")
                        break
                    report(round(index / len(steps) * 100), f"[演示] {step}")
                    if env_id and not any(item["environment_id"] == env_id for item in result["targets"]):
                        result["targets"].append({
                            "environment_id": env_id, "status": "demo", "ready": False
                        })
                else:
                    result.update(
                        status="demo_completed",
                        summary=f"演示完成 · {len(environments)} 个真实环境仍待初始化",
                    )
            elif missing := sorted({environment.kind for environment in environments if environment.kind not in adapters}):
                names = "、".join(missing)
                result.update(status="blocked", summary=f"这些环境类型的真实初始化适配器尚未接入：{names}")
                report(0, result["summary"] + "。为避免部分初始化，本次未操作任何设备。")
            elif cancel.is_set():
                result.update(status="cancelled", summary="已在设备操作前取消")
            else:
                result["action_state"] = "unknown"
                atomic_json(directory / "result.json", result)
                for index, environment in enumerate(environments, start=1):
                    if cancel.is_set():
                        result.update(
                            status="cancelled", ready=False, action_state="completed",
                            summary=f"已停止；{index - 1} 个环境已完成，未继续后续环境",
                        )
                        break
                    report(round((index - 1) / len(environments) * 100),
                           f"开始初始化 [{index}/{len(environments)}] {environment.id} / {environment.kind}")
                    def target_report(progress: int, message: str) -> None:
                        bounded = max(0, min(100, progress))
                        overall = round(((index - 1) + bounded / 100) / len(environments) * 100)
                        report(overall, f"[{environment.id}] {message}")
                    outcome = adapters[environment.kind].initialize(
                        environment, settings, target_report, cancel
                    )
                    if outcome.action_state not in {"completed", "running", "unknown", "not_started"}:
                        raise ValidationError("适配器返回了无效的设备动作状态")
                    if outcome.ready and outcome.action_state != "completed":
                        raise ValidationError("动作未完成不能标记为就绪")
                    result["targets"].append({
                        "environment_id": environment.id,
                        "status": "succeeded" if outcome.ready else "failed",
                        "ready": outcome.ready,
                        "summary": outcome.summary,
                        "action_state": outcome.action_state,
                    })
                    if not outcome.ready:
                        result.update(status="failed", ready=False,
                                      action_state=outcome.action_state, summary=outcome.summary)
                        break
                else:
                    result.update(ready=True, action_state="completed", status="succeeded",
                                  summary=f"{len(environments)} 个环境已完成初始化和就绪检查")
        except Exception as exc:
            # The public message deliberately excludes raw exception details that could contain secrets.
            result.update(status="failed", summary=f"执行异常（{type(exc).__name__}），请检查内部适配器")
            report(0, result["summary"])
        keep_lock = result["action_state"] in {"unknown", "running"}
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        report(100 if result["status"] in {"succeeded", "demo_completed"} else 0, result["summary"])
        atomic_json(directory / "result.json", result)
        return {**result, "directory": str(directory)}
    finally:
        # Never release a lock when an interrupted adapter might still be changing a device.
        if result["action_state"] in {"unknown", "running"}:
            keep_lock = True
        if not keep_lock:
            lock.unlink(missing_ok=True)


def execute(root: Path, environment: Environment, settings: dict[str, str],
            demo: bool, cancel: Event, emit: Callable[[int, str], None],
            adapters: dict[str, Adapter] | None = None, demo_delay: float = 0.45) -> dict:
    """Compatibility wrapper for one-target integrations."""
    return execute_plan(root, [environment], settings, demo, cancel, emit, adapters, demo_delay)
