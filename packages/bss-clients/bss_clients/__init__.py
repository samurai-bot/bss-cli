"""bss-clients — shared HTTP client package for service-to-service calls."""

from .auth import AuthProvider, NoAuthProvider
from .base import BSSClient, set_context
from .catalog import CatalogClient
from .crm import CRMClient
from .errors import ClientError, NotFound, PolicyViolationFromServer, ServerError, Timeout
from .inventory import InventoryClient
from .payment import PaymentClient
from .subscription import SubscriptionClient

__all__ = [
    "AuthProvider",
    "BSSClient",
    "CatalogClient",
    "CRMClient",
    "ClientError",
    "InventoryClient",
    "NoAuthProvider",
    "NotFound",
    "PaymentClient",
    "PolicyViolationFromServer",
    "ServerError",
    "SubscriptionClient",
    "Timeout",
    "set_context",
]
