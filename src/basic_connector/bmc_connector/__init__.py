"""Backend-neutral BMC connector public API."""

from .connector import BmcBackend, BmcConnector
from .errors import (
    BmcConnectionError,
    BmcConnectorError,
    BmcUnsupportedActionError,
)
from .models import (
    BiosSnapshot,
    IssuePolicy,
    PowerAction,
    PowerActionReceipt,
    PowerOperationResult,
    PowerOperationStatus,
    PowerState,
)

__all__ = [
    "BiosSnapshot",
    "BmcBackend",
    "BmcConnectionError",
    "BmcConnector",
    "BmcConnectorError",
    "BmcUnsupportedActionError",
    "IssuePolicy",
    "PowerAction",
    "PowerActionReceipt",
    "PowerOperationResult",
    "PowerOperationStatus",
    "PowerState",
]
