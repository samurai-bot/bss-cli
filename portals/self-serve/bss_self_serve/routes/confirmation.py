"""Confirmation page — /confirmation/{subscription_id}?session=...

v0.11 — reached after the direct-write signup chain's poll route emits
``HX-Redirect``. Renders the eSIM QR PNG + LPA activation code + plan
summary. Subscription data is fetched directly via bss-clients (reads
have always gone direct).

If the in-memory signup session still has the activation code from
the order envelope, we use it; otherwise we fall back to the inventory
client (deep-link from a past activation, or an old code that didn't
surface on the order item). The agent-log widget that v0.4 rendered
here is gone — signup is no longer orchestrator-mediated.
"""

from __future__ import annotations

from ..clients import get_clients
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..offerings import find_plan, flatten_offerings
from ..qrpng import activation_qr_data_uri
from ..templating import templates

router = APIRouter()


@router.get("/confirmation/{subscription_id}", response_class=HTMLResponse)
async def confirmation(
    request: Request, subscription_id: str, session: str
) -> HTMLResponse:
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")

    clients = get_clients()
    subscription = await clients.subscription.get(subscription_id)  # type: ignore[attr-defined]

    activation_code = sig.activation_code
    if not activation_code:
        # Fallback — agent took a tool path that didn't surface the LPA
        # code; derive it from the subscription's ICCID via inventory.
        iccid = subscription.get("iccid") if isinstance(subscription, dict) else None
        if iccid:
            try:
                payload = await clients.inventory.get_activation_code(iccid)  # type: ignore[attr-defined]
                activation_code = payload.get("activation_code") or payload.get(
                    "activationCode"
                )
            except Exception:  # noqa: BLE001
                activation_code = None

    qr_data_uri = activation_qr_data_uri(activation_code) if activation_code else ""

    plans = flatten_offerings(await clients.catalog.list_offerings())
    plan = find_plan(plans, sig.plan)

    return templates.TemplateResponse(
        request,
        "confirmation.html",
        {
            "subscription_id": subscription_id,
            "subscription": subscription,
            "activation_code": activation_code,
            "qr_data_uri": qr_data_uri,
            "plan": plan,
        },
    )
