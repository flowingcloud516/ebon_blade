"""Managed AsyncSSH connector with task-scoped connection reuse."""

from .connector import InteractiveSSHSession, ManagedSSHSession
from .errors import InteractiveProcessExitedError
from .models import (
    CommandRequest,
    CommandResult,
    CompletionPolicy,
    HostKeyPolicy,
    HostKeySettings,
    InteractiveMatchResult,
    InteractiveRequest,
    Matcher,
    ReconnectPolicy,
    RemoteProcessState,
    SSHConfig,
    SessionState,
    TransferResult,
)

__all__ = [
    "CommandRequest", "CommandResult", "CompletionPolicy", "HostKeyPolicy",
    "HostKeySettings", "InteractiveMatchResult", "InteractiveProcessExitedError",
    "InteractiveRequest", "InteractiveSSHSession", "ManagedSSHSession", "Matcher", "ReconnectPolicy",
    "RemoteProcessState", "SSHConfig", "SessionState", "TransferResult",
]
