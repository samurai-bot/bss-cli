"""Promotion repository — dumb reads over the catalog.promotion table (v1.1).

Writes (insert / state transitions) are driven by PromotionService through
the session directly, mirroring CatalogAdminService. This layer only
queries — no business logic, no outward calls.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bss_models.catalog import Promotion


class PromotionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, promotion_id: str) -> Promotion | None:
        stmt = select(Promotion).where(Promotion.id == promotion_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, code: str) -> Promotion | None:
        """Lookup by typed code. Used for create-time uniqueness + preview/validate.

        Codeless targeted promotions have NULL code and are never returned here.
        """
        stmt = select(Promotion).where(Promotion.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_offer_definition_id(self, offer_definition_id: str) -> Promotion | None:
        """The loyalty join-key lookup — promo terms for an entitlement.

        Used by validate-for-order and the targeted-offer display path, which
        start from a loyalty OfferDefinition id and need the BSS money terms.
        """
        stmt = select(Promotion).where(
            Promotion.offer_definition_id == offer_definition_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Promotion]:
        stmt = select(Promotion).order_by(Promotion.id).limit(limit).offset(offset)
        if state is not None:
            stmt = stmt.where(Promotion.state == state)
        return list((await self._session.execute(stmt)).scalars().all())
