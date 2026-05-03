"""Inventory read tools — MSISDN pool + eSIM pool (hosted on CRM).

Reservation / assignment are internal SOM operations and are NOT exposed as
LLM tools — the LLM only reads availability.
"""

from __future__ import annotations

from typing import Any

from ..clients import get_clients
from ..types import Iccid, Msisdn
from ._registry import register


@register("inventory.msisdn.list_available")
async def inventory_msisdn_list_available(
    prefix: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List MSISDNs in state ``available``. Use before ``order.create`` if the
    user asked for a specific prefix or "golden number" pattern.

    Args:
        prefix: Optional digit prefix, e.g. ``"9000"``.
        limit: Maximum rows (default 20).

    Returns:
        List of MSISDN dicts ``{msisdn, state, reservedUntil?}``.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().inventory.list_msisdns(
        state="available", prefix=prefix, limit=limit
    )


@register("inventory.msisdn.get")
async def inventory_msisdn_get(msisdn: Msisdn) -> dict[str, Any]:
    """Get status of a specific MSISDN.

    Args:
        msisdn: 8-digit mobile number.

    Returns:
        MSISDN dict ``{msisdn, state, assignedTo?, reservedUntil?}``.

    Raises:
        NotFound: MSISDN is not in the pool.
    """
    return await get_clients().inventory.get_msisdn(msisdn)


@register("inventory.esim.list_available")
async def inventory_esim_list_available(limit: int = 20) -> list[dict[str, Any]]:
    """List available eSIM profiles. Rarely needed by the LLM — order
    workflow assigns an eSIM automatically.

    Args:
        limit: Maximum rows (default 20).

    Returns:
        List of eSIM dicts ``{iccid, state}``.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().inventory.list_esims(state="available", limit=limit)


@register("inventory.msisdn.add_range")
async def inventory_msisdn_add_range(
    prefix: str, count: int
) -> dict[str, Any]:
    """v0.17 — bulk-extend the MSISDN pool by ``count`` numbers starting
    at ``{prefix}{0:04d}``.

    Operator-only: registered in the ``operator_cockpit`` profile, NOT
    in ``customer_self_serve``. Idempotent on overlap (existing rows
    are preserved).

    Args:
        prefix: 4–7 digit numeric prefix, e.g. ``"9100"``.
        count:  Numbers to add (1..10000).

    Returns:
        ``{prefix, count, inserted, skipped, first, last}``.

    Raises:
        PolicyViolation: bad prefix or count outside bounds.
    """
    return await get_clients().inventory.add_msisdn_range(prefix, count)


@register("inventory.esim.get_activation")
async def inventory_esim_get_activation(iccid: Iccid) -> dict[str, Any]:
    """Return the LPA activation-code record for an eSIM. Callers typically
    want this as ``{iccid, imsi, activationCode, msisdn}`` for QR rendering.
    For a subscription, prefer ``subscription.get_esim_activation`` which
    handles ICCID lookup.

    Args:
        iccid: eSIM ICCID (19-20 digits starting with ``8910101``).

    Returns:
        Activation dict.

    Raises:
        NotFound: unknown ICCID.
    """
    return await get_clients().inventory.get_activation_code(iccid)
