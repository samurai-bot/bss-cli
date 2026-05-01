"""Case thread drill-in — read-only deep link.

Per phases/V0_13_0.md §3.2, the case page is the one v0.5 surface kept
into v0.13: useful for copy-paste case-id deep links from a chat
session, slack, or a runbook. No login dependency anymore — the
cockpit runs single-operator-by-design behind a secure perimeter.

Continues the v0.12 contract: when a case carries
``chat_transcript_hash`` (i.e. it was opened by the customer chat
surface via ``case.open_for_me``), the page renders a "Chat
transcript" panel below the notes. The transcript is fetched via
``CRMClient.get_chat_transcript``.
"""

from __future__ import annotations

import structlog
from bss_clients.errors import ClientError
from bss_cockpit import OPERATOR_ACTOR, current as cockpit_config_current
from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/case/{case_id}", response_class=HTMLResponse)
async def case_thread(request: Request, case_id: str) -> HTMLResponse:
    clients = get_clients()
    try:
        case_raw = await clients.crm.get_case(case_id)
    except ClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
        raise

    tickets = case_raw.get("tickets") or []
    if not tickets:
        try:
            tickets = await clients.crm.list_tickets(case_id=case_id)
        except (ClientError, AttributeError):
            tickets = []

    notes = sorted(
        case_raw.get("notes") or [],
        key=lambda n: n.get("createdAt", ""),
    )

    transcript_hash = (
        case_raw.get("chatTranscriptHash")
        or case_raw.get("chat_transcript_hash")
    )
    transcript_view: dict | None = None
    if transcript_hash:
        try:
            row = await clients.crm.get_chat_transcript(transcript_hash)
            transcript_view = {
                "hash": row.get("hash", transcript_hash),
                "body": row.get("body", ""),
                "recorded_at": row.get("recorded_at", ""),
            }
        except ClientError as exc:
            log.warning(
                "csr.case.chat_transcript_fetch_failed",
                case_id=case_id,
                hash=transcript_hash,
                status=getattr(exc, "status_code", None),
            )
            transcript_view = {
                "hash": transcript_hash,
                "body": None,
                "recorded_at": "",
                "error": "Transcript is no longer retrievable. It may have been archived.",
            }

    cfg = cockpit_config_current()
    return templates.TemplateResponse(
        request,
        "case_thread.html",
        {
            "actor": OPERATOR_ACTOR,
            "model": cfg.settings.llm.model or "(env default)",
            "case": {
                "id": case_raw.get("id", case_id),
                "subject": case_raw.get("subject", ""),
                "state": case_raw.get("state", "unknown"),
                "priority": case_raw.get("priority", ""),
                "category": case_raw.get("category", ""),
                "agent_id": case_raw.get("agentId") or case_raw.get("assignedAgentId"),
                "customer_id": case_raw.get("customerId", ""),
                "created_at": case_raw.get("createdAt", ""),
                "updated_at": case_raw.get("updatedAt", ""),
                "chat_transcript_hash": transcript_hash,
            },
            "tickets": [
                {
                    "id": t.get("id", ""),
                    "type": t.get("ticketType", t.get("type", "")),
                    "subject": t.get("subject", ""),
                    "state": t.get("state", "unknown"),
                    "agent_id": t.get("agentId", ""),
                }
                for t in tickets
            ],
            "notes": [
                {
                    "id": n.get("id", ""),
                    "body": n.get("body", ""),
                    "author": n.get("author") or n.get("createdBy") or "system",
                    "at": n.get("createdAt", ""),
                }
                for n in notes
            ],
            "transcript": transcript_view,
        },
    )
