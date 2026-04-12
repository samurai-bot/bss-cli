"""Test-only endpoints — gated by BSS_ENABLE_TEST_ENDPOINTS.

These are Phase 6 scaffolding and must be removed in Phase 8.
"""

from fastapi import APIRouter, Depends

from app.dependencies import get_subscription_service
from app.schemas.subscription import (
    ConsumeForTestRequest,
    SubscriptionResponse,
    to_subscription_response,
)
from app.services.subscription_service import SubscriptionService

router = APIRouter(tags=["Test Endpoints"])


@router.post(
    "/subscription/{sub_id}/consume-for-test",
    response_model=SubscriptionResponse,
)
async def consume_for_test(
    sub_id: str,
    body: ConsumeForTestRequest,
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionResponse:
    sub = await svc.consume_for_test(sub_id, body.allowance_type, body.quantity)
    return to_subscription_response(sub)
