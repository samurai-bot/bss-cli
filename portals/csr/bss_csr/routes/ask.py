"""POST /customer/{id}/ask — kick off an agent turn.

Just creates the AgentAsk record and 303s back to the customer 360
with ``?session=<sid>``. The 360 page's body-level ``hx-ext="sse"``
opens the stream when ``session_id`` is present; the SSE handler
(``routes/agent_events.py``) is where the agent actually runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ..deps import require_operator
from ..session import OperatorSession

router = APIRouter()


@router.post("/customer/{customer_id}/ask")
async def ask(
    request: Request,
    customer_id: str,
    question: str = Form(...),
    operator: OperatorSession = Depends(require_operator),
) -> RedirectResponse:
    store = request.app.state.agent_ask_store
    ask = await store.create(
        operator_id=operator.operator_id,
        customer_id=customer_id,
        question=question.strip(),
    )
    return RedirectResponse(
        url=f"/customer/{customer_id}?session={ask.session_id}",
        status_code=303,
    )
