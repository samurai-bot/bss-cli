"""GET /agent/events/{session_id} — SSE stream that drives the agent.

Consumes ``agent_bridge.drive_signup``, renders each ``AgentEvent`` as
an HTML partial, and emits it as an SSE frame. The browser swaps each
frame into the DOM via HTMX with zero JavaScript (HTMX's sse extension
handles the plumbing).

This is the only endpoint in the portal that invokes the agent. The
POST /signup handler just stores the form and redirects; *this* route
is where the write actually happens. That keeps the log widget honest
— every tool call shows up, from the very first event.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from bss_orchestrator.session import (
    AgentEvent,
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventToolCallCompleted,
)
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..agent_bridge import drive_signup
from ..agent_render import harvest_ids, project, render_html

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/agent/events/{session_id}")
async def agent_events(request: Request, session_id: str) -> StreamingResponse:
    store = request.app.state.session_store
    sig = await store.get(session_id)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")

    async def stream() -> AsyncIterator[bytes]:
        # If the session already finished, close the stream cleanly
        # with no message frames. The browser's EventSource will try
        # to reconnect every ~3s by default; an empty stream (no
        # data lines) prevents the "complete ✓ complete ✓..." spam
        # the confirmation page used to show after every reconnect.
        # The confirmation page also no longer opens this endpoint —
        # it renders ``sig.event_log`` statically — so this branch is
        # defense-in-depth against stray clients.
        if sig.done:
            yield _sse_frame("status", _status_html("done"))
            return

        yield _sse_frame("status", _status_html("live"))

        try:
            async for event in drive_signup(
                name=sig.name,
                email=sig.email,
                phone=sig.phone,
                plan=sig.plan,
                msisdn=sig.msisdn,
                card_pan=sig.card_pan,
            ):
                _harvest(sig, event)
                # Snapshot the rendered event on the session so the
                # confirmation page can replay the transcript without
                # reopening this stream.
                sig.event_log.append(project(event).__dict__)
                try:
                    yield _sse_frame("message", render_html(event))
                except Exception as exc:  # noqa: BLE001
                    log.warning("agent_events.render_failed", error=str(exc))
                    continue

                if isinstance(event, AgentEventFinalMessage):
                    sig.done = True
                    await store.update(sig)
                    yield _sse_frame("status", _status_html("done"))
                    yield _sse_frame("redirect", _redirect_html(sig))
                    return
                if isinstance(event, AgentEventError):
                    sig.error = event.message
                    await store.update(sig)
                    yield _sse_frame("status", _status_html("error"))
                    return
        except asyncio.CancelledError:
            # Client disconnected — honor it by stopping the stream.
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("agent_events.stream_crashed")
            sig.error = f"{type(exc).__name__}: {exc}"
            await store.update(sig)
            yield _sse_frame("status", _status_html("error"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if it's in front
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Frame helpers
# ─────────────────────────────────────────────────────────────────────────────


def _sse_frame(event_name: str, html_line: str) -> bytes:
    """Encode one SSE frame. HTML must be single-line (agent_render collapses it)."""
    return f"event: {event_name}\ndata: {html_line}\n\n".encode("utf-8")


def _status_html(status: str) -> str:
    dot_class = {
        "live": "dot live",
        "done": "dot done",
        "error": "dot error",
        "idle": "dot idle",
    }.get(status, "dot idle")
    return f'<span class="{dot_class}"></span> {status}'


def _redirect_html(sig) -> str:  # type: ignore[no-untyped-def]
    """OOB fragment that tells the browser where to go next.

    The progress page listens for ``sse-swap="redirect"`` on a hidden
    target and sets ``window.location`` to the URL we return here.
    Activation goes first if we have an order_id (Step 6's progress
    page polls order.get until completed, then redirects to
    /confirmation). If the agent skipped straight to subscription,
    we jump to confirmation directly.
    """
    if sig.order_id:
        return f'<a href="/activation/{sig.order_id}?session={sig.session_id}"></a>'
    if sig.subscription_id:
        return f'<a href="/confirmation/{sig.subscription_id}?session={sig.session_id}"></a>'
    return '<span>done</span>'


def _harvest(sig, event: AgentEvent) -> None:  # type: ignore[no-untyped-def]
    """Scan tool results + final message for IDs and stash them on the session."""
    text: str = ""
    if isinstance(event, AgentEventToolCallCompleted):
        text = event.result or ""
        # JSON parse first (richer than regex) — pick out the primary id
        # by tool namespace so we don't mis-attribute a nested id.
        try:
            parsed = json.loads(text) if text else None
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            cid = parsed.get("id")
            if isinstance(cid, str):
                if event.name.startswith("customer.") and cid.startswith("CUST-") and not sig.customer_id:
                    sig.customer_id = cid
                elif event.name.startswith("order.") and cid.startswith("ORD-") and not sig.order_id:
                    sig.order_id = cid
                elif event.name.startswith("subscription.") and cid.startswith("SUB-") and not sig.subscription_id:
                    sig.subscription_id = cid
            code = (
                parsed.get("activationCode")
                or parsed.get("lpa")
                or parsed.get("activation_code")
            )
            if code and not sig.activation_code:
                sig.activation_code = str(code)
    elif isinstance(event, AgentEventFinalMessage):
        text = event.text or ""
        sig.final_text = text
    else:
        return

    # Regex fallback — covers plain-text tool results and the final message.
    harvested = harvest_ids(text)
    for key, value in harvested.items():
        if not getattr(sig, key, None):
            setattr(sig, key, value)


