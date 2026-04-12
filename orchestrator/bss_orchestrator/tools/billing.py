"""Billing tools — TMF678 Customer Bill. Stubbed in v0.1.

The Billing service itself is a stub until Phase 10; these tools return a
structured ``not-implemented`` error rather than hitting the network. The
LLM sees the error shape and can explain the situation to the user.
"""

from __future__ import annotations

from typing import Any

from ..types import BillId, CustomerId
from ._registry import register

_NOT_IMPLEMENTED = {
    "error": "NOT_IMPLEMENTED",
    "message": (
        "Billing is scaffolded but not implemented in v0.1. "
        "Bills, invoice generation, and period summaries ship in Phase 10."
    ),
}


@register("billing.get_account")
async def billing_get_account(customer_id: CustomerId) -> dict[str, Any]:
    """Read the billing account summary for a customer. NOT IMPLEMENTED in v0.1.

    Args:
        customer_id: Customer ID in CUST-NNN format.

    Returns:
        v0.1: a structured ``NOT_IMPLEMENTED`` error payload. Phase 10
        returns ``{customerId, balance, openBills, nextBillDate}``.

    Raises:
        (none in v0.1 — error-shape returned in band)
    """
    return {**_NOT_IMPLEMENTED, "customerId": customer_id}


@register("billing.list_bills")
async def billing_list_bills(
    customer_id: CustomerId, limit: int = 20
) -> dict[str, Any]:
    """List bills for a customer, newest first. NOT IMPLEMENTED in v0.1.

    Args:
        customer_id: Customer ID in CUST-NNN format.
        limit: Max rows (default 20).

    Returns:
        v0.1: a structured ``NOT_IMPLEMENTED`` error payload.

    Raises:
        (none in v0.1)
    """
    return {**_NOT_IMPLEMENTED, "customerId": customer_id, "limit": limit}


@register("billing.get_bill")
async def billing_get_bill(bill_id: BillId) -> dict[str, Any]:
    """Get a single bill. NOT IMPLEMENTED in v0.1.

    Args:
        bill_id: Bill ID in BILL-NNN format.

    Returns:
        v0.1: a structured ``NOT_IMPLEMENTED`` error payload.

    Raises:
        (none in v0.1)
    """
    return {**_NOT_IMPLEMENTED, "billId": bill_id}


@register("billing.get_current_period")
async def billing_get_current_period(customer_id: CustomerId) -> dict[str, Any]:
    """Return an at-a-glance summary of the customer's current billing period.
    NOT IMPLEMENTED in v0.1.

    Args:
        customer_id: Customer ID in CUST-NNN format.

    Returns:
        v0.1: a structured ``NOT_IMPLEMENTED`` error payload.

    Raises:
        (none in v0.1)
    """
    return {**_NOT_IMPLEMENTED, "customerId": customer_id}
