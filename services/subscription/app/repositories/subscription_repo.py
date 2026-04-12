"""Subscription repository — CRUD + sequence IDs."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bss_models.subscription import BundleBalance, Subscription, SubscriptionStateHistory


class SubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def next_id(self) -> str:
        result = await self._s.execute(
            text("SELECT nextval('subscription.subscription_id_seq')")
        )
        seq = result.scalar_one()
        return f"SUB-{seq:04d}"

    async def create(self, sub: Subscription) -> Subscription:
        self._s.add(sub)
        await self._s.flush()
        return sub

    async def get(self, sub_id: str) -> Subscription | None:
        from sqlalchemy import select

        stmt = (
            select(Subscription)
            .where(Subscription.id == sub_id)
            .options(
                selectinload(Subscription.balances),
                selectinload(Subscription.vas_purchases),
                selectinload(Subscription.state_history),
            )
        )
        result = await self._s.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_msisdn(self, msisdn: str) -> Subscription | None:
        from sqlalchemy import select

        stmt = (
            select(Subscription)
            .where(Subscription.msisdn == msisdn)
            .options(
                selectinload(Subscription.balances),
                selectinload(Subscription.vas_purchases),
            )
        )
        result = await self._s.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_customer(self, customer_id: str) -> list[Subscription]:
        from sqlalchemy import select

        stmt = (
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .options(selectinload(Subscription.balances))
            .order_by(Subscription.created_at.desc())
        )
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def update(self, sub: Subscription) -> Subscription:
        await self._s.flush()
        return sub

    async def add_state_history(self, entry: SubscriptionStateHistory) -> None:
        self._s.add(entry)
        await self._s.flush()

    async def add_balance(self, balance: BundleBalance) -> None:
        self._s.add(balance)
        await self._s.flush()

    async def get_balances(self, sub_id: str) -> list[BundleBalance]:
        from sqlalchemy import select

        stmt = select(BundleBalance).where(BundleBalance.subscription_id == sub_id)
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def update_balance(self, balance: BundleBalance) -> None:
        await self._s.flush()
