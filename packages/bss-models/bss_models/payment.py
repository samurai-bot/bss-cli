"""Payment schema — 2 tables.

payment_method, payment_attempt.
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Numeric, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TZDateTime, TenantMixin, TimestampMixin

SCHEMA = "payment"


class PaymentMethod(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payment_method"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="card")
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    last4: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    exp_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    exp_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")

    attempts: Mapped[list["PaymentAttempt"]] = relationship(back_populates="payment_method")


class PaymentAttempt(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payment_attempt"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    payment_method_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.payment_method.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="SGD")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    gateway_ref: Mapped[str | None] = mapped_column(Text)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    payment_method: Mapped["PaymentMethod"] = relationship(back_populates="attempts")
