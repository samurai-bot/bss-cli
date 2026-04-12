"""Catalog tools — TMF620 product offerings + VAS."""

from __future__ import annotations

from typing import Any

from ..clients import get_clients
from ..types import ProductOfferingId, VasOfferingId
from ._registry import register


@register("catalog.list_offerings")
async def catalog_list_offerings() -> list[dict[str, Any]]:
    """List all product offerings (plans + VAS). In v0.1 there are exactly
    three plans — ``PLAN_S``, ``PLAN_M``, ``PLAN_L`` — plus a handful of VAS.

    Args:
        (none)

    Returns:
        List of offering dicts ``{id, name, price, allowances, type}``.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().catalog.list_offerings()


@register("catalog.get_offering")
async def catalog_get_offering(offering_id: ProductOfferingId) -> dict[str, Any]:
    """Get a single product offering with prices and allowances.

    Args:
        offering_id: Must be ``PLAN_S`` / ``PLAN_M`` / ``PLAN_L``. Other IDs
            come back as not found — there are no other plans in v0.1.

    Returns:
        Offering dict.

    Raises:
        NotFound: unknown offering ID.
    """
    return await get_clients().catalog.get_offering(offering_id)


@register("catalog.list_vas")
async def catalog_list_vas() -> list[dict[str, Any]]:
    """List all VAS (Value-Added Service) offerings — data top-ups, day passes, etc.
    Call this when the user asks to top up a blocked subscription so you can
    pick the right ``vasOfferingId`` for ``subscription.purchase_vas``.

    Args:
        (none)

    Returns:
        List of VAS dicts ``{id, name, price, bundleDelta}``.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().catalog.list_vas()


@register("catalog.get_vas")
async def catalog_get_vas(vas_offering_id: VasOfferingId) -> dict[str, Any]:
    """Get a single VAS offering.

    Args:
        vas_offering_id: VAS offering ID, e.g. ``VAS_DATA_5GB``, ``VAS_DATA_DAYPASS``.

    Returns:
        VAS offering dict.

    Raises:
        NotFound: unknown VAS offering.
    """
    return await get_clients().catalog.get_vas(vas_offering_id)
