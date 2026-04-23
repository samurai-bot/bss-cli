"""Landing page — reads catalog, renders 3 plan cards.

This is a READ endpoint. It does NOT call the agent — listing offerings
is static information that an LLM hop would only delay. The agent is
for writes (see ``agent_bridge.drive_signup``).
"""

from __future__ import annotations

from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..offerings import flatten_offerings
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    clients = get_clients()
    raw = await clients.catalog.list_offerings()
    plans = flatten_offerings(raw)
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"plans": plans},
    )
