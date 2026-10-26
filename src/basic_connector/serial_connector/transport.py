from __future__ import annotations

import asyncio
import socket
from typing import Protocol

from .models import SerialConfig


class SerialTransport(Protocol):
    async def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    async def drain(self) -> None: ...
    async def close(self) -> None: ...


class RawTcpTransport:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect(cls, config: SerialConfig) -> "RawTcpTransport":
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(config.host, config.port), config.connect_timeout
        )
        sock = writer.get_extra_info("socket")
        if sock is not None and config.tcp_keepalive:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        return cls(reader, writer)

    async def read(self, size: int) -> bytes:
        return await self._reader.read(size)

    def write(self, data: bytes) -> None:
        self._writer.write(data)

    async def drain(self) -> None:
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


class RawTcpBackend:
    async def connect(self, config: SerialConfig) -> SerialTransport:
        return await RawTcpTransport.connect(config)
