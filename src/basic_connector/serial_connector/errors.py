class SerialConnectorError(RuntimeError):
    """Base error raised by the network serial connector."""


class SerialConnectionLostError(SerialConnectorError):
    pass


class SerialTimeoutError(SerialConnectorError):
    pass


class SerialIdleTimeoutError(SerialTimeoutError):
    pass


class SerialCancelledError(SerialConnectorError):
    pass


class SerialMatchFailure(SerialConnectorError):
    pass
