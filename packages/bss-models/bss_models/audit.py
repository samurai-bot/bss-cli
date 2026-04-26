"""Audit schema — 1 table.

domain_event (outbox + replay substrate).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TZDateTime

SCHEMA = "audit"


class DomainEvent(Base):
    __tablename__ = "domain_event"
    __table_args__ = (
        Index(
            "ix_domain_event_aggregate_replay",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
        ),
        Index(
            "ix_domain_event_type_time",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_domain_event_unpublished",
            "published_to_mq",
            postgresql_where="NOT published_to_mq",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="DEFAULT", server_default="DEFAULT")
    # v0.9 — resolved at the BSS perimeter from validated token (never
    # from a separate header). "default" / "portal_self_serve" /
    # "partner_<name>". Backfilled to "default" for pre-v0.9 rows.
    service_identity: Mapped[str] = mapped_column(
        Text, nullable=False, default="default", server_default="default"
    )
    payload: Mapped[dict | None] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    published_to_mq: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
