"""Public collectors whose resources are independent of EVB control sessions."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

from basic_connector.serial_connector import (
    ManagedSerialSession,
    SerialConfig,
    SessionMode,
)


class SharedSerialLogCollector:
    """Required observation-only reader for one shared serial-server endpoint."""

    required = True

    def __init__(self, host: str, port: int, log_path: Path, *, connect_timeout: float = 5.0):
        self.session = ManagedSerialSession(
            SerialConfig(
                host=host,
                port=port,
                mode=SessionMode.OBSERVE_ONLY,
                connect_timeout=connect_timeout,
                raw_log_path=log_path,
            )
        )

    async def start(self) -> None:
        await self.session.connect()

    async def stop(self) -> None:
        await self.session.close()


class RequiredParallelCollectorGroup:
    """Start required independent collectors concurrently as one lifecycle unit."""

    required = True

    def __init__(self, collectors: Iterable[object]) -> None:
        self.collectors = tuple(collectors)
        if not self.collectors:
            raise ValueError("a required collector group must not be empty")
        self._started: tuple[object, ...] = ()

    async def start(self) -> None:
        self._started = self.collectors
        try:
            outcomes = await asyncio.gather(
                *(collector.start() for collector in self.collectors),
                return_exceptions=True,
            )
        except BaseException:
            await self.stop()
            raise
        errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if errors:
            await self.stop()
            raise RuntimeError(
                f"{len(errors)} of {len(self.collectors)} required collectors failed to start"
            ) from errors[0]

    async def stop(self) -> None:
        started, self._started = self._started, ()
        if started:
            await asyncio.gather(
                *(collector.stop() for collector in reversed(started)),
                return_exceptions=True,
            )
