"""Minimal explicit lifecycle for long-running environment log collection."""
from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .errors import EnvironmentFrameworkError
from .types import EffectiveEnvironmentConfig


@dataclass(frozen=True)
class LogContext:
    environment_id: str
    config: EffectiveEnvironmentConfig
    directory: Path | None = None
    services: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class LogCollector(Protocol):
    """A collector owns and closes its own observation-only resources."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


async def _invoke(target: Any, method: str) -> None:
    result = getattr(target, method)()
    if inspect.isawaitable(result):
        await result


class LogSession:
    """Environment-scoped collectors which remain open after initialization."""

    def __init__(self, environment_id: str, collectors: tuple[LogCollector, ...]) -> None:
        self.environment_id = environment_id
        self.collectors = collectors
        self.start_errors: list[BaseException] = []
        self.stop_errors: list[BaseException] = []
        self._started: list[LogCollector] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def start(self) -> None:
        if self._closed:
            raise EnvironmentFrameworkError("a closed log session cannot be restarted")
        if self._started:
            return
        for collector in self.collectors:
            try:
                await _invoke(collector, "start")
                self._started.append(collector)
            except BaseException as exc:
                self.start_errors.append(exc)
                try:
                    await _invoke(collector, "stop")
                except BaseException as cleanup_exc:
                    self.stop_errors.append(cleanup_exc)

    async def stop(self) -> tuple[BaseException, ...]:
        if self._closed:
            return tuple(self.stop_errors)
        self._closed = True
        for collector in reversed(self._started):
            try:
                await _invoke(collector, "stop")
            except BaseException as exc:
                self.stop_errors.append(exc)
        self._started.clear()
        return tuple(self.stop_errors)


class LogManager:
    """Run-scoped owner; sessions stop only through explicit lifecycle calls."""

    def __init__(self) -> None:
        self._sessions: dict[str, LogSession] = {}

    @property
    def active_environment_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    def get(self, environment_id: str) -> LogSession | None:
        return self._sessions.get(environment_id)

    async def start_environment_log_session(
        self,
        environment_id: str,
        collectors: tuple[LogCollector, ...],
    ) -> LogSession:
        if environment_id in self._sessions:
            raise EnvironmentFrameworkError(
                f"log session already exists for {environment_id!r}"
            )
        session = LogSession(environment_id, collectors)
        self._sessions[environment_id] = session
        await session.start()
        return session

    async def stop_environment_log_session(self, environment_id: str) -> None:
        session = self._sessions.pop(environment_id, None)
        if session is not None:
            await session.stop()

    async def stop_all(self) -> None:
        for environment_id in reversed(tuple(self._sessions)):
            await self.stop_environment_log_session(environment_id)
