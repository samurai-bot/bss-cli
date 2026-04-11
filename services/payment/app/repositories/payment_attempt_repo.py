"""PaymentAttempt repository — dumb CRUD over ORM + sequence-based ID."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bss_models import PaymentAttempt


class PaymentAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def next_id(self) -> str:
        result = await self._s.execute(
            text("SELECT nextval('payment.payment_attempt_id_seq')")
        )
        seq = result.scalar_one()
        return f"PAY-{seq:06d}"

    async def create(self, attempt: PaymentAttempt) -> PaymentAttempt:
        self._s.add(attempt)
        await self._s.flush()
        return attempt

    async def get(self, attempt_id: str) -> PaymentAttempt | None:
        result = await self._s.execute(
            select(PaymentAttempt).where(PaymentAttempt.id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def list_for_customer(self, customer_id: str) -> list[PaymentAttempt]:
        result = await self._s.execute(
            select(PaymentAttempt)
            .where(PaymentAttempt.customer_id == customer_id)
            .order_by(PaymentAttempt.attempted_at.desc())
        )
        return list(result.scalars().all())
