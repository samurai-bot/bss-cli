"""Stub login — accepts any credentials.

Per V0_5_0.md §3 + §Security model, this is NOT real auth. It exists
to populate ``operator_id`` so the audit trail attributes agent-driven
actions to a human. Real auth ships in Phase 12 (OAuth via Keycloak /
Cognito / Entra).
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..session import SESSION_COOKIE
from ..templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(default=""),
) -> RedirectResponse:
    # Any non-empty username works in dev mode. Password ignored.
    operator_id = (username or "operator").strip()[:64]
    store = request.app.state.session_store
    session = await store.create(operator_id=operator_id)
    response = RedirectResponse(url="/search", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        httponly=True,
        samesite="lax",
        # No secure=True — demo runs on plain HTTP behind Tailscale/LAN.
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await request.app.state.session_store.delete(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
