"""TMF676 Payment Management router — no business logic."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_payment_service
from app.schemas.tmf.payment import (
    PaymentAttemptResponse,
    PaymentChargeRequest,
    to_payment_attempt_response,
)
from app.services.payment_service import PaymentService

router = APIRouter(tags=["payment"])


@router.post(
    "/payment",
    response_model=PaymentAttemptResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def charge(
    body: PaymentChargeRequest,
    svc: PaymentService = Depends(get_payment_service),
) -> PaymentAttemptResponse:
    attempt = await svc.charge(
        customer_id=body.customer_id,
        payment_method_id=body.payment_method_id,
        amount=body.amount,
        currency=body.currency,
        purpose=body.purpose,
    )
    return to_payment_attempt_response(attempt)


@router.get(
    "/payment/{attempt_id}",
    response_model=PaymentAttemptResponse,
    response_model_by_alias=True,
)
async def get_payment(
    attempt_id: str,
    svc: PaymentService = Depends(get_payment_service),
) -> PaymentAttemptResponse:
    attempt = await svc.get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail=f"Payment attempt {attempt_id} not found")
    return to_payment_attempt_response(attempt)


@router.get(
    "/payment",
    response_model=list[PaymentAttemptResponse],
    response_model_by_alias=True,
)
async def list_payments(
    customerId: str,
    svc: PaymentService = Depends(get_payment_service),
) -> list[PaymentAttemptResponse]:
    attempts = await svc.list_attempts(customerId)
    return [to_payment_attempt_response(a) for a in attempts]
