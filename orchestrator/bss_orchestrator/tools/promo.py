"""Promotion tools — operator/admin promo management (v1.1).

These compose over loyalty-cli through the catalog service. Operator-only by
doctrine: ``promo.create`` / ``promo.assign`` are in the ``operator_cockpit``
(and ``default``) profiles, NEVER ``customer_self_serve`` — a customer can
*type* a code at checkout but cannot enumerate or self-issue promotions.
``order.create`` carries the typed-code path for customers.
"""

from __future__ import annotations

from typing import Any

from ..clients import get_clients
from ..types import (
    CustomerId,
    DiscountType,
    DurationKind,
    ProductOfferingId,
    PromoCodeKind,
    PromotionId,
)
from ._registry import register


@register("promo.create")
async def promo_create(
    promotion_id: PromotionId,
    discount_type: DiscountType,
    discount_value: str,
    duration_kind: DurationKind,
    currency: str = "SGD",
    code: str | None = None,
    promo_code_kind: PromoCodeKind | None = None,
    applicable_offering_ids: list[ProductOfferingId] | None = None,
    periods_total: int | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Create a promotion (two-system saga: BSS money terms + loyalty entitlement).

    Operator/admin only. Writes the catalog money terms, registers the loyalty
    OfferDefinition, and (for a typed code) the promo code — then flips active.

    Args:
        promotion_id: Stable id, e.g. ``PROMO_SUMMER25``. Used as the loyalty
            idempotency key; a retry resumes a half-finished saga.
        discount_type: ``percent`` or ``absolute``.
        discount_value: Amount as a string (Decimal-safe). Percent must be 0-100.
        duration_kind: ``single`` (activation period only), ``multi`` (N periods,
            requires ``periods_total`` >= 2), or ``perpetual`` (never reverts).
        currency: ISO-4217 for absolute discounts. Default SGD.
        code: Typed code for a NON-targeted promo. Omit for a codeless targeted
            promo (assign later with ``promo.assign``).
        promo_code_kind: Required when ``code`` is set —
            ``single_use_shared`` | ``multi_use`` | ``single_use_unique_per_customer``.
        applicable_offering_ids: Restrict to these plans. Omit = all sellable.
        periods_total: Required for ``multi`` (>= 2); omit otherwise.
        valid_from / valid_to: Optional ISO-8601 validity window.
        display_name: Optional human label (defaults to the promotion id).

    Returns:
        The promotion dict with ``state="active"`` and ``offerDefinitionId`` set.

    Raises:
        PolicyViolationFromServer:
            - ``catalog.promotion.already_exists`` / ``code_in_use``
            - ``catalog.promotion.invalid_*`` (discount/duration/code validation)
            - ``catalog.promotion.loyalty_refused`` (translated loyalty refusal)
    """
    return await get_clients().catalog.create_promotion(
        promotion_id=promotion_id,
        discount_type=discount_type,
        discount_value=discount_value,
        duration_kind=duration_kind,
        currency=currency,
        code=code,
        promo_code_kind=promo_code_kind,
        applicable_offering_ids=applicable_offering_ids,
        periods_total=periods_total,
        valid_from=valid_from,
        valid_to=valid_to,
        display_name=display_name,
    )


@register("promo.assign")
async def promo_assign(
    promotion_id: PromotionId,
    customer_ids: list[CustomerId],
) -> dict[str, Any]:
    """Assign a codeless (targeted) promotion to specific customers.

    Operator/admin only — this is the targeting "simulator": one loyalty
    ``offer.issue`` per customer. The offer auto-applies at the customer's next
    order and shows on their dashboard; no code is typed. Re-runnable — a
    customer who already has the offer is reported under ``skipped``.

    Args:
        promotion_id: An ``active`` promotion id (created via ``promo.create``).
        customer_ids: The chosen audience (CUST- prefixed).

    Returns:
        ``{promotionId, offerDefinitionId, issued: [...], skipped: [...]}``.

    Raises:
        PolicyViolationFromServer:
            - ``catalog.promotion.not_active``: promotion missing or not linked.
    """
    return await get_clients().catalog.assign_promotion(
        promotion_id, customer_ids=customer_ids
    )


@register("promo.show")
async def promo_show(promotion_id: PromotionId) -> dict[str, Any]:
    """Read a promotion's money terms + loyalty link + state.

    Args:
        promotion_id: The promotion id.

    Returns:
        The promotion dict (discount terms, code, offerDefinitionId, state).

    Raises:
        NotFound: no such promotion.
    """
    return await get_clients().catalog.get_promotion(promotion_id)
