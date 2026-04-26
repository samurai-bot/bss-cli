"""Confirmation page — /confirmation/{subscription_id}?session=...

Reached after the agent has placed the order and the subscription
is active. Renders the eSIM QR PNG + LPA activation code + plan
summary. Subscription data is fetched directly via bss-clients
(read path — no agent needed).

If the user arrives with a valid session (the common path from the
redirect event), the session already carries the activation code
and we skip re-fetching it. If they somehow arrived without one
(deep-linking from a past run), we try the inventory client.
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

    # Render the agent's full transcript statically from the session —
    # the confirmation page must NOT open a live SSE connection, or
    # the browser would reconnect every ~3s and the widget would fill
    # with repeated "complete" frames.
    events = [
        {**e, "detail": e.get("detail_full") or e.get("detail", "")}
        for e in sig.event_log
    ]

    return templates.TemplateResponse(
        request,
        "confirmation.html",
        {
            "session_id": None,
            "stream_live": False,
            "agent_log_status": "error" if sig.error else "done",
            "events": events,
            "subscription_id": subscription_id,
            "subscription": subscription,
            "activation_code": activation_code,
            "qr_data_uri": qr_data_uri,
            "plan": plan,
            "final_text": sig.final_text,
        },
    )
