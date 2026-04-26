"""Portal auth schema — 4 tables.

identity, login_token, session, login_attempt.

This schema is portal-side identity, deliberately separate from
``crm`` (which owns the BSS-core customer record). An ``identity``
becomes linked to a ``customer`` only when the signup funnel
completes its first KYC + ``customer.create`` (see
``link_to_customer`` in the bss-portal-auth public API). Until then,
``customer_id`` is NULL and the visitor sees the empty dashboard.
"""

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TZDateTime, TenantMixin

SCHEMA = "portal_auth"


class Identity(Base, TenantMixin):
    """A verified email maps to one identity, optionally linked to a customer."""

    __tablename__ = "identity"
    __table_args__ = (
        # Same email can't have two active identities; only `deleted` is excluded
        # from the uniqueness check, so soft-deleted rows don't block re-signup.
        Index(
            "uq_identity_email_active",
            "email",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unverified", server_default="unverified"
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class LoginToken(Base, TenantMixin):
    """Active login challenge — OTP, magic_link, or step_up."""

    __tablename__ = "login_token"
    __table_args__ = (
        Index(
            "ix_login_token_identity_kind_unconsumed",
            "identity_id",
            "kind",
            "consumed_at",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.identity.id"), nullable=False
    )
    # 'magic_link' | 'otp' | 'step_up'
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional scope binding for step_up tokens (e.g. "subscription.terminate").
    # Null for magic_link / otp; never null for step_up.
    action_label: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)


class Session(Base, TenantMixin):
    """Server-side session — the cookie value is just this row's id."""

    __tablename__ = "session"
    __table_args__ = (
        Index("ix_session_identity_active", "identity_id", "revoked_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.identity.id"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class LoginAttempt(Base, TenantMixin):
    """Append-only audit + rate-limit substrate.

    `outcome` ∈ {success, wrong_code, expired, no_active_token,
    rate_limited, no_such_identity}. Entries are queried by
    (email, ip, ts) windows to enforce per-email and per-IP caps.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_email_ts", "email", "ts"),
        Index("ix_login_attempt_ip_ts", "ip", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional discriminator: 'login_start', 'login_verify', 'step_up_start',
    # 'step_up_verify'. Helps the rate-limiter scope its window queries.
    stage: Mapped[str | None] = mapped_column(Text)
