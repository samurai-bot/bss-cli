"""Order Management (COM) schema — 3 tables.

product_order, order_item, order_state_history.
"""

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TZDateTime, TenantMixin, TimestampMixin

SCHEMA = "order_mgmt"


class ProductOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_order"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="acknowledged")
    order_date: Mapped[datetime | None] = mapped_column(TZDateTime)
    requested_completion_date: Mapped[datetime | None] = mapped_column(TZDateTime)
    completed_date: Mapped[datetime | None] = mapped_column(TZDateTime)
    msisdn_preference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    state_history: Mapped[list["OrderStateHistory"]] = relationship(back_populates="order")


class OrderItem(Base, TenantMixin, TimestampMixin):
    __tablename__ = "order_item"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_order.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    offering_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str | None] = mapped_column(Text)
    target_subscription_id: Mapped[str | None] = mapped_column(Text)

    order: Mapped["ProductOrder"] = relationship(back_populates="items")


class OrderStateHistory(Base, TenantMixin):
    __tablename__ = "order_state_history"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.product_order.id"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    order: Mapped["ProductOrder"] = relationship(back_populates="state_history")
