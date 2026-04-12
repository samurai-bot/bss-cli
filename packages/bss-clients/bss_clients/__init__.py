"""bss-clients — shared HTTP client package for service-to-service calls."""

from .auth import AuthProvider, NoAuthProvider
from .base import BSSClient, set_context
from .billing import BillingClient
from .catalog import CatalogClient
from .com import COMClient
from .crm import CRMClient
from .errors import ClientError, NotFound, PolicyViolationFromServer, ServerError, Timeout
from .inventory import InventoryClient
from .mediation import MediationClient
from .payment import PaymentClient
from .provisioning import ProvisioningClient
from .som import SOMClient
from .subscription import SubscriptionClient

__all__ = [
    "AuthProvider",
    "BSSClient",
    "BillingClient",
    "COMClient",
    "CRMClient",
    "CatalogClient",
    "ClientError",
    "InventoryClient",
    "MediationClient",
    "NoAuthProvider",
    "NotFound",
    "PaymentClient",
    "PolicyViolationFromServer",
    "ProvisioningClient",
    "SOMClient",
    "ServerError",
    "SubscriptionClient",
    "Timeout",
    "set_context",
]
