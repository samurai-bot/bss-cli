"""Subscription API routers — no business logic."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_subscription_service
from app.schemas.subscription import (
    BundleBalanceResponse,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    VasPurchaseRequest,
    to_balance_response,
    to_subscription_response,
)
from app.services.subscription_service import SubscriptionService

router = APIRouter(tags=["Subscription"])


@router.post("/subscription", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: SubscriptionCreateRequest,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.create(
        customer_id=body.customer_id,
        offering_id=body.offering_id,
        msisdn=body.msisdn,
        iccid=body.iccid,
        payment_method_id=body.payment_method_id,
    )
    return to_subscription_response(sub)


@router.get("/subscription/{sub_id}", response_model=SubscriptionResponse)
async def get_subscription(
    sub_id: str,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail=f"Subscription {sub_id} not found")
    return to_subscription_response(sub)


@router.get("/subscription", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    customerId: str | None = None,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> list[SubscriptionResponse]:
    if not customerId:
        raise HTTPException(status_code=400, detail="customerId query param is required")
    subs = await svc.list_for_customer(customerId)
    return [to_subscription_response(s) for s in subs]


@router.get("/subscription/by-msisdn/{msisdn}", response_model=SubscriptionResponse)
async def get_by_msisdn(
    msisdn: str,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.get_by_msisdn(msisdn)
    if not sub:
        raise HTTPException(status_code=404, detail=f"No subscription for MSISDN {msisdn}")
    return to_subscription_response(sub)


@router.get("/subscription/{sub_id}/balance", response_model=list[BundleBalanceResponse])
async def get_balance(
    sub_id: str,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> list[BundleBalanceResponse]:
    balances = await svc.get_balances(sub_id)
    if not balances:
        raise HTTPException(status_code=404, detail=f"No balances for {sub_id}")
    return [to_balance_response(b) for b in balances]


@router.post("/subscription/{sub_id}/vas-purchase", response_model=SubscriptionResponse)
async def purchase_vas(
    sub_id: str,
    body: VasPurchaseRequest,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.purchase_vas(sub_id, body.vas_offering_id)
    return to_subscription_response(sub)


@router.post("/subscription/{sub_id}/renew", response_model=SubscriptionResponse)
async def renew_subscription(
    sub_id: str,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.renew(sub_id)
    return to_subscription_response(sub)


@router.post("/subscription/{sub_id}/terminate", response_model=SubscriptionResponse)
async def terminate_subscription(
    sub_id: str,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.terminate(sub_id)
    return to_subscription_response(sub)
