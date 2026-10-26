from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Pattern


class CompletionPolicy(str, Enum):
    EXIT_REQUIRED = "exit_required"
    EXPECT_REQUIRED = "expect_required"
    EXIT_OR_EXPECT = "exit_or_expect"


class SessionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    SUSPECT = "suspect"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class RemoteProcessState(str, Enum):
    EXITED = "exited"
    RUNNING = "running"
    UNKNOWN = "unknown"


class HostKeyPolicy(str, Enum):
    STRICT = "strict"
    ENVIRONMENT_PINNED = "environment_pinned"
    REPLACE_AFTER_VERIFY = "replace_after_verify"
    RESET_FOR_REPROVISION = "reset_for_reprovision"
    INSECURE_ACCEPT_ANY = "insecure_accept_any"


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
    jitter: float = 0.2


@dataclass(frozen=True)
class HostKeySettings:
    environment_id: str
    store_path: Path
    policy: HostKeyPolicy = HostKeyPolicy.ENVIRONMENT_PINNED
    rotation_authorized: bool = False


@dataclass(frozen=True)
class SSHConfig:
    host: str
    username: str
    password: str = field(repr=False)
    port: int = 22
    connect_timeout: float = 15.0
    login_timeout: float = 30.0
    keepalive_interval: float = 15.0
    keepalive_count_max: int = 3
    reconnect: ReconnectPolicy = field(default_factory=ReconnectPolicy)
    host_keys: HostKeySettings | None = None

    def __post_init__(self) -> None:
        if not self.host or not self.username or not self.password:
            raise ValueError("host, username and password are required")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.keepalive_interval < 0 or self.keepalive_count_max < 1:
            raise ValueError("invalid keepalive settings")


@dataclass(frozen=True)
class CommandRequest:
    command: str
    completion: CompletionPolicy = CompletionPolicy.EXIT_REQUIRED
    expected: tuple[Matcher, ...] = ()
    failure: tuple[Matcher, ...] = ()
    total_timeout: float = 600.0
    idle_timeout: float | None = None
    side_effect: bool = False
    retryable: bool = False
    encoding: str = "utf-8"
    output_tail_limit: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must not be empty")
        if self.total_timeout <= 0:
            raise ValueError("total_timeout must be positive")
        if self.completion is CompletionPolicy.EXPECT_REQUIRED and not self.expected:
            raise ValueError("EXPECT_REQUIRED needs at least one expected matcher")
        if self.retryable and self.side_effect:
            raise ValueError("a side-effecting command cannot be automatically retryable")


@dataclass(frozen=True)
class CommandResult:
    succeeded: bool
    trigger: str
    exit_status: int | None
    matched: str | None
    stdout_tail: str
    stderr_tail: str
    remote_process_state: RemoteProcessState


@dataclass(frozen=True)
class TransferResult:
    source: str
    destination: str
    bytes_transferred: int | None
    verified: bool
