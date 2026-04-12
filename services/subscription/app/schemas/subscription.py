"""Subscription Pydantic schemas — camelCase for API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from bss_models.subscription import BundleBalance, Subscription, VasPurchase

SUBSCRIPTION_PATH = "/subscription-api/v1/subscription"


class SubscriptionCreateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    customer_id: str
    offering_id: str
    msisdn: str
    iccid: str
    payment_method_id: str


class VasPurchaseRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    vas_offering_id: str


class ConsumeForTestRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    allowance_type: str = "data"
    quantity: int


class BundleBalanceResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    subscription_id: str
    allowance_type: str
    total: int
    consumed: int
    remaining: int
    unit: str
    period_start: datetime | None = None
    period_end: datetime | None = None


class VasPurchaseResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    subscription_id: str
    vas_offering_id: str
    payment_attempt_id: str | None = None
    applied_at: datetime | None = None
    expires_at: datetime | None = None
    allowance_added: int
    allowance_type: str


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    href: str
    customer_id: str
    offering_id: str
    msisdn: str
    iccid: str
    cfs_service_id: str | None = None
    state: str
    state_reason: str | None = None
    activated_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    next_renewal_at: datetime | None = None
    terminated_at: datetime | None = None
    balances: list[BundleBalanceResponse] = []
    at_type: str = "Subscription"


def to_balance_response(b: BundleBalance) -> BundleBalanceResponse:
    return BundleBalanceResponse(
        id=b.id,
        subscription_id=b.subscription_id,
        allowance_type=b.allowance_type,
        total=b.total,
        consumed=b.consumed,
        remaining=b.total - b.consumed if b.total >= 0 else -1,
        unit=b.unit,
        period_start=b.period_start,
        period_end=b.period_end,
    )


def to_subscription_response(sub: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        href=f"{SUBSCRIPTION_PATH}/{sub.id}",
        customer_id=sub.customer_id,
        offering_id=sub.offering_id,
        msisdn=sub.msisdn,
        iccid=sub.iccid,
        cfs_service_id=sub.cfs_service_id,
        state=sub.state,
        state_reason=sub.state_reason,
        activated_at=sub.activated_at,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        next_renewal_at=sub.next_renewal_at,
        terminated_at=sub.terminated_at,
        balances=[to_balance_response(b) for b in sub.balances] if sub.balances else [],
    )


def to_vas_purchase_response(vp: VasPurchase) -> VasPurchaseResponse:
    return VasPurchaseResponse(
        id=vp.id,
        subscription_id=vp.subscription_id,
        vas_offering_id=vp.vas_offering_id,
        payment_attempt_id=vp.payment_attempt_id,
        applied_at=vp.applied_at,
        expires_at=vp.expires_at,
        allowance_added=vp.allowance_added,
        allowance_type=vp.allowance_type,
    )
