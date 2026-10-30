"""Task-scoped access to framework-managed control connectors."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigurationError, ContextClosedError
from .types import EffectiveEnvironmentConfig, StepResult


class ControlContext:
    def __init__(
        self,
        config: EffectiveEnvironmentConfig,
        connectors: Mapping[str, Any],
        *,
        cancel_event: asyncio.Event | None = None,
        run_directory: Path | None = None,
    ) -> None:
        if set(connectors) - set(config.connections):
            raise ConfigurationError("connector supplied without matching connection config")
        self.config = config
        self.environment_id = config.environment_id
        self.connections = dict(config.connections)
        self._connectors = dict(connectors)
        self.cancel_event = cancel_event or asyncio.Event()
        self.run_directory = run_directory
        self.step_results: dict[str, StepResult] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def resolve_connection(
        self,
        connection_id: str,
        *,
        connector_type: str | None = None,
    ) -> Any:
        if self._closed:
            raise ContextClosedError("control context has already been closed")
        config = self.connections.get(connection_id)
        if config is None or connection_id not in self._connectors:
            raise ConfigurationError(f"unknown or unavailable connection: {connection_id}")
        if connector_type is not None and config.connector_type != connector_type:
            raise ConfigurationError(
                f"connection {connection_id!r} is {config.connector_type!r}, "
                f"not {connector_type!r}"
            )
        return self._connectors[connection_id]

    def record_step_result(self, step_id: str, result: StepResult) -> None:
        self.step_results[step_id] = result

    async def close(self) -> tuple[BaseException, ...]:
        """Close each owned connector once; cleanup errors are returned, not raised."""
        if self._closed:
            return ()
        self._closed = True
        errors: list[BaseException] = []
        seen: set[int] = set()
        for connector in reversed(tuple(self._connectors.values())):
            if id(connector) in seen:
                continue
            seen.add(id(connector))
            close = getattr(connector, "close", None)
            if close is None:
                continue
            try:
                outcome = close()
                if inspect.isawaitable(outcome):
                    await outcome
            except BaseException as exc:  # cleanup must not mask the control result
                errors.append(exc)
        self._connectors.clear()
        return tuple(errors)

    async def __aenter__(self) -> "ControlContext":
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()
