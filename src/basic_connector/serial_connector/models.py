from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Pattern


class SessionMode(str, Enum):
    CONTROL = "control"
    OBSERVE_ONLY = "observe_only"


class SessionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    SUSPECT = "suspect"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class CompletionPolicy(str, Enum):
    EXPECT_REQUIRED = "expect_required"
    PROMPT_REQUIRED = "prompt_required"
    QUIET_AFTER_EXPECT = "quiet_after_expect"
    WRITE_ONLY = "write_only"


MatcherCallback = Callable[[str], bool]


@dataclass(frozen=True)
class Matcher:
    value: str | Pattern[str] | MatcherCallback
    name: str = "expected"

    def matches(self, text: str) -> bool:
        if isinstance(self.value, str):
            return self.value in text
        if hasattr(self.value, "search"):
            return bool(self.value.search(text))
        return bool(self.value(text))


@dataclass(frozen=True)
class ReconnectPolicy:
    delays: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)


@dataclass(frozen=True)
class SerialConfig:
    host: str
    port: int
    mode: SessionMode = SessionMode.CONTROL
    connect_timeout: float = 10.0
    line_ending: bytes = b"\r"
    probe_expected: tuple[Matcher, ...] = ()
    probe_timeout: float = 10.0
    encoding: str = "utf-8"
    decode_errors: str = "replace"
    read_size: int = 4096
    buffer_limit: int = 256 * 1024
    raw_log_path: Path | None = None
    tcp_keepalive: bool = True
    reconnect: ReconnectPolicy = field(default_factory=ReconnectPolicy)

    def __post_init__(self) -> None:
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("valid host and port are required")
        if self.connect_timeout <= 0 or self.probe_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.read_size <= 0 or self.buffer_limit <= 0:
            raise ValueError("buffer sizes must be positive")
        if self.mode is SessionMode.OBSERVE_ONLY and self.probe_expected:
            raise ValueError("OBSERVE_ONLY cannot use a write-based connection probe")


@dataclass(frozen=True)
class SerialCommandRequest:
    command: str | None = None
    raw_bytes: bytes | None = None
    line_ending: bytes | None = None
    expected: tuple[Matcher, ...] = ()
    failure: tuple[Matcher, ...] = ()
    completion: CompletionPolicy = CompletionPolicy.EXPECT_REQUIRED
    prompt: Matcher | None = None
    total_timeout: float = 600.0
    idle_timeout: float | None = None
    quiet_period: float = 1.0
    output_tail_limit: int = 64 * 1024

    def __post_init__(self) -> None:
        if (self.command is None) == (self.raw_bytes is None):
            raise ValueError("provide exactly one of command or raw_bytes")
        if self.total_timeout <= 0 or (self.idle_timeout is not None and self.idle_timeout <= 0):
            raise ValueError("timeouts must be positive")
        if self.completion is CompletionPolicy.EXPECT_REQUIRED and not self.expected:
            raise ValueError("EXPECT_REQUIRED needs an expected matcher")
        if self.completion is CompletionPolicy.PROMPT_REQUIRED and self.prompt is None:
            raise ValueError("PROMPT_REQUIRED needs a prompt matcher")
        if self.completion is CompletionPolicy.QUIET_AFTER_EXPECT and not self.expected:
            raise ValueError("QUIET_AFTER_EXPECT needs an expected matcher")
        if self.quiet_period <= 0:
            raise ValueError("quiet_period must be positive")


@dataclass(frozen=True)
class SerialResult:
    succeeded: bool
    trigger: str
    matched: str | None
    output_tail: str
    connection_recovered: bool = False
