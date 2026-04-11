"""Catalog schema — 7 tables.

product_specification, product_offering, product_offering_price,
bundle_allowance, vas_offering, service_specification, product_to_service_mapping.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TZDateTime, TenantMixin, TimestampMixin

SCHEMA = "catalog"


class ProductSpecification(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_specification"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str | None] = mapped_column(Text)

    offerings: Mapped[list["ProductOffering"]] = relationship(back_populates="specification")


class ProductOffering(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_offering"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    spec_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_specification.id")
    )
    is_bundle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_sellable: Mapped[bool | None] = mapped_column(Boolean)
    lifecycle_status: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(TZDateTime)
    valid_to: Mapped[datetime | None] = mapped_column(TZDateTime)

    specification: Mapped["ProductSpecification | None"] = relationship(back_populates="offerings")
    prices: Mapped[list["ProductOfferingPrice"]] = relationship(back_populates="offering")
    allowances: Mapped[list["BundleAllowance"]] = relationship(back_populates="offering")
    service_mappings: Mapped[list["ProductToServiceMapping"]] = relationship(back_populates="offering")


class ProductOfferingPrice(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_offering_price"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    offering_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_offering.id"), nullable=False
    )
    price_type: Mapped[str] = mapped_column(Text, nullable=False)
    recurring_period_length: Mapped[int | None] = mapped_column(SmallInteger)
    recurring_period_type: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="SGD")

    offering: Mapped["ProductOffering"] = relationship(back_populates="prices")


class BundleAllowance(Base, TenantMixin, TimestampMixin):
    __tablename__ = "bundle_allowance"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    offering_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_offering.id"), nullable=False
    )
    allowance_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)

    offering: Mapped["ProductOffering"] = relationship(back_populates="allowances")


class VasOffering(Base, TenantMixin, TimestampMixin):
    __tablename__ = "vas_offering"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    price_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="SGD")
    allowance_type: Mapped[str | None] = mapped_column(Text)
    allowance_quantity: Mapped[int | None] = mapped_column(BigInteger)
    allowance_unit: Mapped[str | None] = mapped_column(Text)
    expiry_hours: Mapped[int | None] = mapped_column(SmallInteger)


class ServiceSpecification(Base, TenantMixin, TimestampMixin):
    __tablename__ = "service_specification"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict | None] = mapped_column(JSONB)


class ProductToServiceMapping(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_to_service_mapping"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_offering.id"), nullable=False
    )
    cfs_spec_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.service_specification.id"), nullable=False
    )
    rfs_spec_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    offering: Mapped["ProductOffering"] = relationship(back_populates="service_mappings")
