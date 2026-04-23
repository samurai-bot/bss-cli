"""GET /agent/events/{session_id} — SSE stream for the CSR ask flow.

Same shape as the self-serve portal's stream:
- One ``event: status`` (live) at the start
- One ``event: message`` per AgentEvent (HTML partial from
  ``bss_portal_ui.agent_log.render_html``)
- After the final message: ``event: status`` (done) + ``event:
  agent-complete`` (empty payload — pure trigger). The customer 360
  page's auto-refresh sections listen for ``sse:agent-complete from:body``
  and re-fetch.

If the ask is already done (browser reconnect after stream closure),
emits a single ``status: done`` and closes — no more event-log replay,
no spam.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from bss_orchestrator.session import AgentEventError, AgentEventFinalMessage
from bss_portal_ui.agent_log import project, render_html
from bss_portal_ui.sse import format_frame as _sse_frame
from bss_portal_ui.sse import status_html as _status_html
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..agent_bridge import ask_about_customer
from ..deps import require_operator
from ..session import OperatorSession

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/agent/events/{session_id}")
async def agent_events(
    request: Request,
    session_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> StreamingResponse:
    store = request.app.state.agent_ask_store
    ask = await store.get(session_id)
    if ask is None:
        raise HTTPException(status_code=404, detail="Unknown or expired ask session.")

    async def stream() -> AsyncIterator[bytes]:
        if ask.done:
            yield _sse_frame("status", _status_html("done"))
            return

        yield _sse_frame("status", _status_html("live"))

        try:
            async for event in ask_about_customer(
                customer_id=ask.customer_id,
                question=ask.question,
                operator_id=ask.operator_id,
            ):
                ask.event_log.append(project(event).__dict__)
                try:
                    yield _sse_frame("message", render_html(event))
                except Exception as exc:  # noqa: BLE001
                    log.warning("csr.agent_events.render_failed", error=str(exc))
                    continue

                if isinstance(event, AgentEventFinalMessage):
                    ask.done = True
                    ask.final_text = event.text or ""
                    yield _sse_frame("status", _status_html("done"))
                    # Empty payload — the body-level swap target's
                    # ``hx-trigger="sse:agent-complete from:body"`` fires
                    # the customer 360 sections to re-fetch.
                    yield _sse_frame("agent-complete", " ")
                    return
                if isinstance(event, AgentEventError):
                    ask.error = event.message
                    yield _sse_frame("status", _status_html("error"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("csr.agent_events.stream_crashed")
            ask.error = f"{type(exc).__name__}: {exc}"
            yield _sse_frame("status", _status_html("error"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
