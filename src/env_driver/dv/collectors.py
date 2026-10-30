"""DV log collectors with resources independent of control sessions."""
from pathlib import Path

from basic_connector.serial_connector import ManagedSerialSession, SerialConfig, SessionMode


class DvSerialLogCollector:
    required = True

    def __init__(
        self,
        host: str,
        port: int,
        log_path: Path,
        *,
        connect_timeout: float = 5.0,
    ) -> None:
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
