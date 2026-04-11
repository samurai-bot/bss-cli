from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bss_models.catalog import (
    BundleAllowance,
    ProductOffering,
    ProductOfferingPrice,
    ProductSpecification,
    VasOffering,
)


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_offerings(
        self,
        *,
        lifecycle_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ProductOffering]:
        stmt = (
            select(ProductOffering)
            .options(
                selectinload(ProductOffering.specification),
                selectinload(ProductOffering.prices),
                selectinload(ProductOffering.allowances),
            )
            .limit(limit)
            .offset(offset)
            .order_by(ProductOffering.id)
        )
        if lifecycle_status:
            stmt = stmt.where(ProductOffering.lifecycle_status == lifecycle_status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_offering(self, offering_id: str) -> ProductOffering | None:
        stmt = (
            select(ProductOffering)
            .options(
                selectinload(ProductOffering.specification),
                selectinload(ProductOffering.prices),
                selectinload(ProductOffering.allowances),
            )
            .where(ProductOffering.id == offering_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_specifications(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ProductSpecification]:
        stmt = (
            select(ProductSpecification)
            .limit(limit)
            .offset(offset)
            .order_by(ProductSpecification.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_specification(self, spec_id: str) -> ProductSpecification | None:
        stmt = select(ProductSpecification).where(ProductSpecification.id == spec_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_vas_offerings(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[VasOffering]:
        stmt = (
            select(VasOffering)
            .limit(limit)
            .offset(offset)
            .order_by(VasOffering.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_vas_offering(self, vas_id: str) -> VasOffering | None:
        stmt = select(VasOffering).where(VasOffering.id == vas_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
