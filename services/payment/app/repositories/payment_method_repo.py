"""PaymentMethod repository — dumb CRUD over ORM + sequence-based ID."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bss_models import PaymentMethod


class PaymentMethodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def next_id(self) -> str:
        result = await self._s.execute(
            text("SELECT nextval('payment.payment_method_id_seq')")
        )
        seq = result.scalar_one()
        return f"PM-{seq:04d}"

    async def create(self, pm: PaymentMethod) -> PaymentMethod:
        self._s.add(pm)
        await self._s.flush()
        return pm

    async def get(self, pm_id: str) -> PaymentMethod | None:
        result = await self._s.execute(
            select(PaymentMethod).where(PaymentMethod.id == pm_id)
        )
        return result.scalar_one_or_none()

    async def list_for_customer(
        self, customer_id: str, *, include_removed: bool = False
    ) -> list[PaymentMethod]:
        stmt = select(PaymentMethod).where(
            PaymentMethod.customer_id == customer_id
        )
        if not include_removed:
            stmt = stmt.where(PaymentMethod.status == "active")
        stmt = stmt.order_by(PaymentMethod.created_at.desc())
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def count_active_for_customer(self, customer_id: str) -> int:
        result = await self._s.execute(
            select(func.count())
            .select_from(PaymentMethod)
            .where(
                PaymentMethod.customer_id == customer_id,
                PaymentMethod.status == "active",
            )
        )
        return result.scalar_one()

    async def update(self, pm: PaymentMethod) -> PaymentMethod:
        await self._s.flush()
        return pm
