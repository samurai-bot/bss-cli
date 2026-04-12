"""bss-clients factory — single place where clients are constructed.

Tools and CLI commands call ``get_clients()`` rather than constructing clients
themselves. This ensures base URLs come from one config source and swapping
an endpoint (e.g. local vs docker-compose hostnames) is a one-line change.

Clients are lazily built once per process and cached in a ``Clients`` dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from bss_clients import (
    BillingClient,
    COMClient,
    CRMClient,
    CatalogClient,
    InventoryClient,
    MediationClient,
    PaymentClient,
    ProvisioningClient,
    SOMClient,
    SubscriptionClient,
)

from .config import settings


@dataclass(frozen=True)
class Clients:
    """Container for every downstream service client."""

    catalog: CatalogClient
    crm: CRMClient
    inventory: InventoryClient
    payment: PaymentClient
    com: COMClient
    som: SOMClient
    subscription: SubscriptionClient
    mediation: MediationClient
    provisioning: ProvisioningClient
    billing: BillingClient


@lru_cache(maxsize=1)
def get_clients() -> Clients:
    """Return the process-wide ``Clients`` bundle (constructed on first call)."""
    return Clients(
        catalog=CatalogClient(base_url=settings.catalog_url),
        crm=CRMClient(base_url=settings.crm_url),
        # Inventory lives inside CRM (port 8002) — same base URL.
        inventory=InventoryClient(base_url=settings.crm_url),
        payment=PaymentClient(base_url=settings.payment_url),
        com=COMClient(base_url=settings.com_url),
        som=SOMClient(base_url=settings.som_url),
        subscription=SubscriptionClient(base_url=settings.subscription_url),
        mediation=MediationClient(base_url=settings.mediation_url),
        provisioning=ProvisioningClient(base_url=settings.provisioning_url),
        billing=BillingClient(base_url=settings.billing_url),
    )


async def close_clients() -> None:
    """Close every client in the cached bundle (CLI shutdown hook)."""
    if get_clients.cache_info().currsize == 0:
        return
    c = get_clients()
    for client in (
        c.catalog,
        c.crm,
        c.inventory,
        c.payment,
        c.com,
        c.som,
        c.subscription,
        c.mediation,
        c.provisioning,
        c.billing,
    ):
        await client.close()
    get_clients.cache_clear()
