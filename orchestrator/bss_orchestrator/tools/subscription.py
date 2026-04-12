"""Subscription tools — balance, VAS, renewal, termination, eSIM activation."""

from __future__ import annotations

from typing import Any

from ..clients import get_clients
from ..types import CustomerId, SubscriptionId, VasOfferingId
from ._registry import register


@register("subscription.get")
async def subscription_get(subscription_id: SubscriptionId) -> dict[str, Any]:
    """Read a subscription with bundle balances + renewal info. This is the
    go-to diagnostic read — the ``state`` field tells you whether the service
    is active, blocked, or terminated.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        Subscription dict ``{id, customerId, offeringId, msisdn, iccid,
        state, balances, nextRenewalAt}``. ``balances`` is a list of
        ``{type, used, total, unit}`` rows — ``total=None`` means unlimited.

    Raises:
        NotFound: unknown subscription.
    """
    return await get_clients().subscription.get(subscription_id)


@register("subscription.list_for_customer")
async def subscription_list_for_customer(
    customer_id: CustomerId,
) -> list[dict[str, Any]]:
    """List a customer's subscriptions.

    Args:
        customer_id: Customer ID in CUST-NNN format.

    Returns:
        List of subscription summary dicts. Call ``subscription.get`` for full detail.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().subscription.list_for_customer(customer_id)


@register("subscription.get_balance")
async def subscription_get_balance(subscription_id: SubscriptionId) -> dict[str, Any]:
    """Read bundle balances for a subscription. Use this before offering a
    VAS top-up — the user wants to know ``used / total`` for each resource.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        Balance dict ``{subscriptionId, balances: [{type, used, total, unit}]}``.

    Raises:
        NotFound: unknown subscription.
    """
    return await get_clients().subscription.get_balance(subscription_id)


@register("subscription.purchase_vas")
async def subscription_purchase_vas(
    subscription_id: SubscriptionId,
    vas_offering_id: VasOfferingId,
) -> dict[str, Any]:
    """Purchase a VAS (Value-Added Service) for a subscription and charge
    the customer's default card-on-file. Use this when a customer is blocked
    due to bundle exhaustion and wants to top up, or when they want to add
    extra allowance to an active subscription.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.
        vas_offering_id: VAS offering ID (e.g. ``VAS_DATA_5GB``). Get this
            from ``catalog.list_vas`` — do not guess.

    Returns:
        Updated subscription dict. If the subscription was ``blocked``, expect
        it to be ``active`` now. Check ``balances`` for the updated allowance.

    Raises:
        PolicyViolationFromServer:
            - ``subscription.vas_purchase.requires_active_cof``: customer has
              no active card. Fix with ``payment.add_card``, then retry.
            - ``subscription.vas_purchase.vas_offering_sellable``: VAS offering
              is inactive. Ask ``catalog.list_vas`` for valid IDs.
            - ``subscription.vas_purchase.not_if_terminated``: subscription is
              terminated; not recoverable.
    """
    return await get_clients().subscription.purchase_vas(
        subscription_id, vas_offering_id
    )


@register("subscription.terminate")
async def subscription_terminate(subscription_id: SubscriptionId) -> dict[str, Any]:
    """Terminate a subscription — releases MSISDN, recycles eSIM. DESTRUCTIVE —
    gated by ``safety.py``.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        Updated subscription dict with ``state="terminated"``.

    Raises:
        PolicyViolationFromServer:
            - ``subscription.terminate.already_terminated``.
    """
    return await get_clients().subscription.terminate(subscription_id)


@register("subscription.renew_now")
async def subscription_renew_now(subscription_id: SubscriptionId) -> dict[str, Any]:
    """Manually trigger a subscription renewal (charges COF, resets balances).
    Normal renewals happen automatically on the period boundary — use this
    only for edge cases.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        Updated subscription dict with fresh ``balances`` and new ``nextRenewalAt``.

    Raises:
        PolicyViolationFromServer:
            - ``subscription.renew.requires_active_cof``: no valid card; fix
              with ``payment.add_card`` then retry.
    """
    return await get_clients().subscription.renew(subscription_id)


@register("subscription.get_esim_activation")
async def subscription_get_esim_activation(
    subscription_id: SubscriptionId,
) -> dict[str, Any]:
    """Return the LPA activation-code bundle for a subscription's eSIM. Use
    this for first-time QR display after activation, or when the customer
    needs to re-install the eSIM profile.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        ``{subscriptionId, iccid, imsi, activationCode, msisdn}``. The
        ``activationCode`` is the LPA string (``LPA:1$...``).

    Raises:
        NotFound: no eSIM attached to this subscription.
    """
    return await get_clients().subscription.get_esim_activation(subscription_id)
