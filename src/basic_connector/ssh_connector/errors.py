class SSHConnectorError(RuntimeError):
    """Base error safe for callers to classify."""


class HostKeyError(SSHConnectorError):
    pass


class ConnectionLostError(SSHConnectorError):
    pass


class CommandTimeoutError(SSHConnectorError):
    pass


class CommandIdleTimeoutError(CommandTimeoutError):
    pass


class CommandCancelledError(SSHConnectorError):
    pass


class InteractiveProcessExitedError(SSHConnectorError):
    pass
