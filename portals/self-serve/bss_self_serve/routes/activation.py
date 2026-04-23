"""Activation progress page — /activation/{order_id}?session=...

By the time the user lands here, the SSE stream has usually already
finished and the session knows the subscription_id + activation code,
so we jump straight to /confirmation. If the user arrived early (or
refreshed) and the order is not yet done, we render a polling shell
that refreshes itself via HTMX until ``order.get`` reports
``state == completed``.
"""

from __future__ import annotations

from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..templating import templates

router = APIRouter()


@router.get("/activation/{order_id}", response_class=HTMLResponse)
async def activation(request: Request, order_id: str, session: str) -> HTMLResponse:
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")

    if sig.subscription_id:
        return RedirectResponse(
            url=f"/confirmation/{sig.subscription_id}?session={session}",
            status_code=303,
        )

    # Early arrival — render a tiny polling shell. HTMX fetches the
    # status fragment every second; once the order completes and the
    # session has a subscription_id, the fragment redirects via HX-Redirect.
    return templates.TemplateResponse(
        request,
        "activation.html",
        {
            "session_id": session,
            "stream_live": True,  # the agent may still be running
            "order_id": order_id,
            "plan_id": sig.plan,
        },
    )


@router.get("/activation/{order_id}/status", response_class=HTMLResponse)
async def activation_status(
    request: Request, order_id: str, session: str
) -> HTMLResponse:
    """Polled fragment — returns a stepper partial or triggers redirect."""
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")

    if sig.subscription_id:
        # HTMX honors ``HX-Redirect`` to navigate the whole page.
        resp = HTMLResponse(content="")
        resp.headers["HX-Redirect"] = f"/confirmation/{sig.subscription_id}?session={session}"
        return resp

    # Still running — read fresh state from COM for the stepper.
    clients = get_clients()
    try:
        order = await clients.com.get_order(order_id)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — best-effort; poll again next tick
        order = {"state": "in_progress"}

    state = str(order.get("state") or "in_progress")
    return templates.TemplateResponse(
        request,
        "partials/activation_stepper.html",
        {"state": state, "order_id": order_id, "session_id": session},
    )
