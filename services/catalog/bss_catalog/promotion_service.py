"""Promotion service — the v1.1 create saga + reads (catalog side).

Catalog owns the *money terms* (the ``promotion`` row) and the link to
loyalty-cli, which owns the *entitlement* (OfferDefinition + codes/offers).
``create_promotion`` is a two-system saga; this service is the only place
that holds the ``LoyaltyClient``.

Saga ordering (BSS row first, loyalty next, BSS confirm last) makes a crash
harmless: a live code/offer does nothing until the promotion row is
``active``, so a half-failed saga never leaves a usable code pointing at
missing money terms. A retry with the same ``promotion_id`` resumes from
``pending_link`` — the loyalty calls carry ``Idempotency-Key=promotion_id``
so they replay rather than duplicate.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import structlog
from bss_clients import LoyaltyClient, PolicyViolationFromServer
from sqlalchemy.ext.asyncio import AsyncSession

from bss_catalog.policies import PolicyViolation
from bss_catalog.promotion_repository import PromotionRepository
from bss_catalog.services import _check_admin
from bss_models.catalog import Promotion

log = structlog.get_logger()

_DISCOUNT_TYPES = {"percent", "absolute"}
_DURATION_KINDS = {"single", "multi", "perpetual"}
# loyalty PromoCodeKind (verified against :8080/openapi.json).
_PROMO_CODE_KINDS = {
    "single_use_unique_per_customer",
    "single_use_shared",
    "multi_use",
}


def _offer_definition_id_for(promotion_id: str) -> str:
    """Deterministic loyalty OD id for a promotion. Deterministic so a saga
    retry re-registers the same OD (idempotent) and ``reconcile`` can relink.
    """
    return f"OD_{promotion_id}"


class PromotionService:
    def __init__(
        self,
        session: AsyncSession,
        repo: PromotionRepository,
        loyalty: LoyaltyClient,
        actor: str,
    ) -> None:
        self._session = session
        self._repo = repo
        self._loyalty = loyalty
        self._actor = actor

    # ── reads ────────────────────────────────────────────────────────────

    async def get(self, promotion_id: str) -> Promotion | None:
        return await self._repo.get(promotion_id)

    async def get_by_offer_definition_id(self, offer_definition_id: str) -> Promotion | None:
        return await self._repo.get_by_offer_definition_id(offer_definition_id)

    # ── create saga ────────────────────────────────────────────────────────

    async def create_promotion(
        self,
        *,
        promotion_id: str,
        discount_type: str,
        discount_value: Decimal,
        duration_kind: str,
        currency: str = "SGD",
        code: str | None = None,
        promo_code_kind: str | None = None,
        applicable_offering_ids: list[str] | None = None,
        periods_total: int | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        display_name: str | None = None,
    ) -> Promotion:
        """Create money terms + register the loyalty entitlement (two-system saga).

        ``code`` set = non-targeted (a typed, shared/multi-use code);
        ``code`` None = codeless targeted promo (assigned later via offer.issue).
        """
        _check_admin(self._actor)
        self._validate(
            discount_type=discount_type,
            discount_value=discount_value,
            duration_kind=duration_kind,
            periods_total=periods_total,
            code=code,
            promo_code_kind=promo_code_kind,
        )

        existing = await self._repo.get(promotion_id)
        if existing is not None and existing.state != "pending_link":
            raise PolicyViolation(
                rule="catalog.promotion.already_exists",
                message=f"Promotion {promotion_id} already exists (state={existing.state})",
                context={"promotion_id": promotion_id, "state": existing.state},
            )
        if existing is None and code is not None:
            clash = await self._repo.get_by_code(code)
            if clash is not None:
                raise PolicyViolation(
                    rule="catalog.promotion.code_in_use",
                    message=f"Promo code {code} is already bound to promotion {clash.id}",
                    context={"code": code, "promotion_id": clash.id},
                )

        # ── step 1: write (or resume) the pending_link row ──────────────
        if existing is None:
            promo = Promotion(
                id=promotion_id,
                code=code,
                offer_definition_id=None,
                discount_type=discount_type,
                discount_value=discount_value,
                currency=currency,
                applicable_offering_ids=applicable_offering_ids,
                duration_kind=duration_kind,
                periods_total=periods_total,
                valid_from=valid_from,
                valid_to=valid_to,
                state="pending_link",
                created_by=self._actor,
            )
            self._session.add(promo)
            await self._session.commit()
            log.info("catalog.promotion.pending", promotion_id=promotion_id, actor=self._actor)
        else:
            promo = existing  # resume a half-finished saga

        # ── steps 2-3: register the loyalty entitlement ─────────────────
        od_id = _offer_definition_id_for(promotion_id)
        try:
            await self._loyalty.register_offer_definition(
                definition_id=od_id,
                display_name=display_name or promotion_id,
                idempotency_key=promotion_id,
            )
            if code is not None:
                await self._loyalty.register_promo_code(
                    code=code,
                    offer_definition_id=od_id,
                    kind=promo_code_kind,
                    idempotency_key=promotion_id,
                )
        except PolicyViolationFromServer as exc:
            # Leave the row pending_link (harmless — no live entitlement points
            # at it yet) and surface as a catalog policy violation so the
            # middleware renders the standard 422 envelope.
            raise PolicyViolation(
                rule="catalog.promotion.loyalty_refused",
                message=f"loyalty refused: {exc.detail}",
                context={"promotion_id": promotion_id, "loyalty_rule": exc.rule},
            ) from exc

        # ── step 4: confirm the link ────────────────────────────────────
        promo.offer_definition_id = od_id
        promo.state = "active"
        await self._session.commit()
        log.info(
            "catalog.promotion.created",
            promotion_id=promotion_id,
            offer_definition_id=od_id,
            code=code,
            actor=self._actor,
        )
        await self._session.refresh(promo)
        return promo

    # ── validation ───────────────────────────────────────────────────────

    @staticmethod
    def _validate(
        *,
        discount_type: str,
        discount_value: Decimal,
        duration_kind: str,
        periods_total: int | None,
        code: str | None,
        promo_code_kind: str | None,
    ) -> None:
        if discount_type not in _DISCOUNT_TYPES:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_discount_type",
                message=f"discount_type must be one of {sorted(_DISCOUNT_TYPES)}",
                context={"discount_type": discount_type},
            )
        if discount_value <= 0:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_discount_value",
                message="discount_value must be positive",
                context={"discount_value": str(discount_value)},
            )
        if discount_type == "percent" and discount_value > 100:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_discount_value",
                message="percent discount cannot exceed 100",
                context={"discount_value": str(discount_value)},
            )
        if duration_kind not in _DURATION_KINDS:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_duration_kind",
                message=f"duration_kind must be one of {sorted(_DURATION_KINDS)}",
                context={"duration_kind": duration_kind},
            )
        if duration_kind == "multi":
            if periods_total is None or periods_total < 2:
                raise PolicyViolation(
                    rule="catalog.promotion.invalid_periods_total",
                    message="multi-period promo requires periods_total >= 2",
                    context={"periods_total": periods_total},
                )
        elif periods_total is not None:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_periods_total",
                message=f"{duration_kind} promo must not set periods_total",
                context={"duration_kind": duration_kind, "periods_total": periods_total},
            )
        if code is not None and promo_code_kind not in _PROMO_CODE_KINDS:
            raise PolicyViolation(
                rule="catalog.promotion.invalid_promo_code_kind",
                message=f"a coded promo requires promo_code_kind in {sorted(_PROMO_CODE_KINDS)}",
                context={"promo_code_kind": promo_code_kind},
            )
