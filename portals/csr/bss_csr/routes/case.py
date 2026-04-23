"""Case thread drill-in — read-only.

V0_5_0.md §6: shows a single case with its child tickets and the
notes timeline. No writes; if the operator needs to add a note or
transition a ticket, they ask the agent on the parent customer 360.
"""

from __future__ import annotations

import asyncio

from bss_clients.errors import ClientError
from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..deps import require_operator
from ..session import OperatorSession
from ..templating import templates

router = APIRouter()


@router.get("/case/{case_id}", response_class=HTMLResponse)
async def case_thread(
    request: Request,
    case_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    clients = get_clients()
    try:
        case_raw = await clients.crm.get_case(case_id)
    except ClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
        raise

    # Tickets may already be inline on the case payload; if not, fetch
    # them via the list endpoint. Notes the same way.
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

    return templates.TemplateResponse(
        request,
        "case_thread.html",
        {
            "operator": operator,
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
        },
    )
