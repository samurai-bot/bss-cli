"""Signup form — GET renders, POST creates a session and redirects.

The POST handler does NOT invoke the agent directly. It stores the
form input in the in-memory session store and redirects the user to
the progress page, which then opens the SSE stream that drives the
agent (see ``routes/agent_events.py``). Keeping the agent invocation
behind the SSE stream is what lets the log widget show every tool
call from the very first event.

v0.8: every entry point in this module is gated on
``Depends(requires_verified_email)`` — anonymous purchase is not a
supported path. The verified identity is pulled from
``request.state.identity`` and stashed on the in-memory signup
session as ``identity_id`` so the agent stream can call
``link_to_customer`` the moment ``customer.create`` returns.
"""

from __future__ import annotations

from bss_orchestrator.clients import get_clients
from bss_portal_auth import IdentityView
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..offerings import find_plan, flatten_offerings
from ..prompts import KYC_PREBAKED_ATTESTATION_ID
from ..security import requires_verified_email
from ..templating import templates

router = APIRouter()


@router.get("/signup/{plan_id}", response_class=HTMLResponse)
async def signup_form(
    request: Request,
    plan_id: str,
    msisdn: str = Query(default=..., pattern=r"^[0-9]{6,15}$"),
    identity: IdentityView = Depends(requires_verified_email),
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
            "identity_email": identity.email,
        },
    )


def _format_msisdn(msisdn: str) -> str:
    if len(msisdn) == 8 and msisdn.isdigit():
        return f"+65 {msisdn[:4]} {msisdn[4:]}"
    return msisdn


@router.get("/signup/{plan_id}/progress", response_class=HTMLResponse)
async def signup_progress(
    request: Request,
    plan_id: str,
    session: str,
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    # Defence-in-depth: a logged-in user shouldn't be able to peek at
    # someone else's in-flight signup by guessing the session id.
    if sig.identity_id and sig.identity_id != identity.id:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    return templates.TemplateResponse(
        request,
        "progress.html",
        {
            "session_id": session,
            "stream_live": True,
            "signup": sig,
            "plan_id": plan_id,
        },
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
    identity: IdentityView = Depends(requires_verified_email),
) -> RedirectResponse:
    store = request.app.state.session_store
    session = await store.create(
        plan=plan,
        name=name,
        email=email,
        phone=phone,
        msisdn=msisdn,
        card_pan=card_pan,
        identity_id=identity.id,
    )
    # 303 flips a POST → GET on the redirect, which is what we want.
    return RedirectResponse(
        url=f"/signup/{plan}/progress?session={session.session_id}",
        status_code=303,
    )
