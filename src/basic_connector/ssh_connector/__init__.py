"""Managed AsyncSSH connector with task-scoped connection reuse."""

from .connector import ManagedSSHSession
from .models import (
    CommandRequest,
    CommandResult,
    CompletionPolicy,
    HostKeyPolicy,
    HostKeySettings,
    Matcher,
    ReconnectPolicy,
    RemoteProcessState,
    SSHConfig,
    SessionState,
    TransferResult,
)

__all__ = [
    "CommandRequest", "CommandResult", "CompletionPolicy", "HostKeyPolicy",
    "HostKeySettings", "ManagedSSHSession", "Matcher", "ReconnectPolicy",
    "RemoteProcessState", "SSHConfig", "SessionState", "TransferResult",
]
