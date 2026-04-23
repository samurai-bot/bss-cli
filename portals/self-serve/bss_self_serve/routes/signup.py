"""Signup form — GET renders, POST creates a session and redirects.

The POST handler does NOT invoke the agent directly. It stores the
form input in the in-memory session store and redirects the user to
the progress page, which then opens the SSE stream that drives the
agent (see ``routes/agent_events.py`` — wired in Step 5). Keeping the
agent invocation behind the SSE stream is what lets the log widget
show every tool call from the very first event.
"""

from __future__ import annotations

from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..offerings import find_plan, flatten_offerings
from ..prompts import KYC_PREBAKED_ATTESTATION_ID
from ..templating import templates

router = APIRouter()


@router.get("/signup/{plan_id}", response_class=HTMLResponse)
async def signup_form(
    request: Request,
    plan_id: str,
    msisdn: str = Query(default=..., pattern=r"^[0-9]{6,15}$"),
) -> HTMLResponse:
    clients = get_clients()
    raw = await clients.catalog.list_offerings()
    plan = find_plan(flatten_offerings(raw), plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {plan_id}")
    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "plan": plan,
            "msisdn": msisdn,
            "msisdn_display": _format_msisdn(msisdn),
            "kyc_attestation_id": KYC_PREBAKED_ATTESTATION_ID,
        },
    )


def _format_msisdn(msisdn: str) -> str:
    if len(msisdn) == 8 and msisdn.isdigit():
        return f"+65 {msisdn[:4]} {msisdn[4:]}"
    return msisdn


@router.get("/signup/{plan_id}/progress", response_class=HTMLResponse)
async def signup_progress(request: Request, plan_id: str, session: str) -> HTMLResponse:
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    return templates.TemplateResponse(
        request,
        "progress.html",
        {"session_id": session, "signup": sig, "plan_id": plan_id},
    )


@router.post("/signup")
async def signup_submit(
    request: Request,
    plan: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    msisdn: str = Form(...),
    card_pan: str = Form(...),
) -> RedirectResponse:
    store = request.app.state.session_store
    session = await store.create(
        plan=plan,
        name=name,
        email=email,
        phone=phone,
        msisdn=msisdn,
        card_pan=card_pan,
    )
    # 303 flips a POST → GET on the redirect, which is what we want.
    return RedirectResponse(
        url=f"/signup/{plan}/progress?session={session.session_id}",
        status_code=303,
    )
