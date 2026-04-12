"""MSISDN pool repository."""

from datetime import datetime, timezone

from bss_clock import now as clock_now
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bss_models.inventory import MsisdnPool


class MsisdnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, msisdn: str) -> MsisdnPool | None:
        result = await self._s.execute(
            select(MsisdnPool).where(MsisdnPool.msisdn == msisdn)
        )
        return result.scalar_one_or_none()

    async def list_msisdns(
        self,
        *,
        status: str | None = None,
        prefix: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MsisdnPool]:
        stmt = select(MsisdnPool).limit(limit).offset(offset).order_by(MsisdnPool.msisdn)
        if status:
            stmt = stmt.where(MsisdnPool.status == status)
        if prefix:
            stmt = stmt.where(MsisdnPool.msisdn.startswith(prefix))
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def reserve_atomic(
        self, msisdn: str, tenant_id: str
    ) -> MsisdnPool | None:
        """Atomically reserve a specific MSISDN using FOR UPDATE SKIP LOCKED."""
        result = await self._s.execute(
            text("""
                SELECT msisdn FROM inventory.msisdn_pool
                WHERE msisdn = :m AND status = 'available' AND tenant_id = :t
                FOR UPDATE SKIP LOCKED
            """),
            {"m": msisdn, "t": tenant_id},
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        await self._s.execute(
            text("""
                UPDATE inventory.msisdn_pool
                SET status = 'reserved', reserved_at = :now, updated_at = :now
                WHERE msisdn = :m
            """),
            {"m": msisdn, "now": clock_now()},
        )
        # Re-fetch as ORM object
        return await self.get(msisdn)

    async def reserve_next_available(self, tenant_id: str) -> MsisdnPool | None:
        """Reserve the next available MSISDN atomically."""
        result = await self._s.execute(
            text("""
                SELECT msisdn FROM inventory.msisdn_pool
                WHERE status = 'available' AND tenant_id = :t
                ORDER BY msisdn LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
            {"t": tenant_id},
        )
        msisdn = result.scalar_one_or_none()
        if not msisdn:
            return None
        await self._s.execute(
            text("""
                UPDATE inventory.msisdn_pool
                SET status = 'reserved', reserved_at = :now, updated_at = :now
                WHERE msisdn = :m
            """),
            {"m": msisdn, "now": clock_now()},
        )
        return await self.get(msisdn)

    async def update_status(self, msisdn: str, status: str) -> MsisdnPool | None:
        row = await self.get(msisdn)
        if row:
            row.status = status
            if status == "available":
                row.reserved_at = None
                row.assigned_to_subscription_id = None
            await self._s.flush()
        return row
