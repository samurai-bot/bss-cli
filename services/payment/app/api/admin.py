"""Payment admin router — wipes the ``payment`` schema + v0.16 cutover."""

from __future__ import annotations

from bss_admin import ResetPlan, TableReset, admin_router
from fastapi import Depends, Query

from app.dependencies import get_payment_method_service
from app.services.payment_method_service import PaymentMethodService

_OPERATIONAL = (
    TableReset("payment_attempt"),
    TableReset("payment_method"),
)

router = admin_router(
    service_name="payment",
    plans=[ResetPlan(schema="payment", tables=_OPERATIONAL)],
)


# v0.16 — cutover endpoint. Operator-only, gated by BSS_API_TOKEN at the
# perimeter. The CLI (`bss payment cutover --invalidate-mock-tokens`)
# calls it; no portal route surfaces this. Kept on the existing admin
# router so the same `/admin-api/v1` prefix + same auth applies.
@router.post("/cutover/invalidate-mock-tokens")
async def cutover_invalidate_mock_tokens(
    dry_run: bool = Query(False, alias="dryRun"),
    svc: PaymentMethodService = Depends(get_payment_method_service),
):
    """Mark every active mock-token payment method as expired.

    Use BEFORE flipping ``BSS_PAYMENT_PROVIDER=mock → stripe`` in
    production. Without this (or the lazy-fail recovery path), the
    first charge against any pre-cutover saved card silently fails
    weeks after the switch.
    """
    return await svc.cutover_invalidate_mock_tokens(dry_run=dry_run)
