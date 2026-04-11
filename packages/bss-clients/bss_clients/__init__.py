"""bss-clients — shared HTTP client package for service-to-service calls."""

from .auth import AuthProvider, NoAuthProvider
from .base import BSSClient, set_context
from .catalog import CatalogClient
from .crm import CRMClient
from .errors import ClientError, NotFound, PolicyViolationFromServer, ServerError, Timeout
from .payment import PaymentClient

__all__ = [
    "AuthProvider",
    "BSSClient",
    "CatalogClient",
    "CRMClient",
    "ClientError",
    "NoAuthProvider",
    "NotFound",
    "PaymentClient",
    "PolicyViolationFromServer",
    "ServerError",
    "Timeout",
    "set_context",
]
