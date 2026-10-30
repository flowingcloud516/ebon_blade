class BmcConnectorError(RuntimeError):
    """Base BMC error which never embeds credentials."""


class BmcUnsupportedActionError(BmcConnectorError):
    pass


class BmcConnectionError(BmcConnectorError):
    pass
