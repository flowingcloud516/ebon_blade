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


def execute(root: Path, environment: Environment, settings: dict[str, str],
            demo: bool, cancel: Event, emit: Callable[[int, str], None],
            adapters: dict[str, Adapter] | None = None, demo_delay: float = 0.45) -> dict:
    environment = deepcopy(environment)
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
    result = {"run_id": run_id, "environment_id": environment.id, "demo": demo,
              "ready": False, "status": "running", "action_state": "not_started",
              "summary": "", "started_at": datetime.now(timezone.utc).isoformat()}
    keep_lock = False

    def report(progress: int, message: str) -> None:
        with (directory / "execution.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        emit(progress, message)

    try:
        directory.mkdir(parents=True)
        from dataclasses import asdict
        atomic_json(directory / "snapshot.json", redact({
            "environment": asdict(environment), "settings": settings, "demo": demo
        }))
        atomic_json(directory / "result.json", result)
        try:
            if demo:
                report(0, "离线演示：不会连接设备、复制固件或执行任何脚本。")
                for progress, step in [(15, "读取配置快照"), (35, "模拟目标检查"),
                                       (55, "模拟环境启动"), (80, "模拟初始化"), (100, "保存演示结果")]:
                    if cancel.wait(demo_delay):
                        result.update(status="cancelled", summary="演示已停止，未操作任何设备")
                        break
                    report(progress, f"[演示] {step}")
                else:
                    result.update(status="demo_completed", summary="演示完成 · 真实环境仍待初始化")
            elif environment.kind not in adapters:
                result.update(status="blocked", summary="此环境的真实初始化适配器尚未接入")
                report(0, result["summary"] + "。请按内部对接文档实现，未操作设备。")
            elif cancel.is_set():
                result.update(status="cancelled", summary="已在设备操作前取消")
            else:
                result["action_state"] = "unknown"
                atomic_json(directory / "result.json", result)
                outcome = adapters[environment.kind].initialize(environment, settings, report, cancel)
                if outcome.action_state not in {"completed", "running", "unknown", "not_started"}:
                    raise ValidationError("适配器返回了无效的设备动作状态")
                if outcome.ready and outcome.action_state != "completed":
                    raise ValidationError("动作未完成不能标记为就绪")
                result.update(ready=outcome.ready, action_state=outcome.action_state,
                              status="succeeded" if outcome.ready else "failed", summary=outcome.summary)
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
