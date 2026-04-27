"""Customer chat surface (v0.12 PR7).

The only orchestrator-mediated route in the self-serve portal — every
other route writes directly via bss-clients per the v0.10 / v0.11
doctrine. The doctrine guard ``check-chat-only`` in the Makefile
asserts ``astream_once`` appears only here.

Three routes:

* ``GET /chat`` — the chat page. When ``?session=<sid>``, the page
  body opens an SSE stream to ``/chat/events/{sid}`` via HTMX. When
  ``?cap_tripped=<reason>``, the page renders a templated banner
  explaining the cap and a retry-at hint.

* ``POST /chat/message`` — form submission. Reads
  ``request.state.customer_id`` (verified session), runs
  ``chat_caps.check_caps``, and either:
  - 303s to ``/chat?cap_tripped=<reason>&retry_at=<iso>`` on trip, or
  - creates a ChatTurn and 303s to ``/chat?session=<sid>``.
  Doctrine: cap-trip never invokes the LLM; the customer sees the
  templated message, never a raw error.

* ``GET /chat/events/{sid}`` — SSE response. Reads the turn from
  the store, fetches the customer + a snapshot of their primary
  subscription for the prompt, then runs:
    astream_once(
        actor=customer_id,
        channel="portal-chat",
        service_identity="portal_self_serve",
        tool_filter="customer_self_serve",
        system_prompt=customer_chat_prompt(...),
        transcript=running_text,
    )
  Each event is rendered to an HTML SSE frame via
  ``bss_portal_ui.agent_log.render_html``. On
  ``AgentEventTurnUsage``, ``chat_caps.record_chat_turn`` records
  the cost. On ``AgentOwnershipViolation`` (surfaced as a generic
  ``AgentEventError`` with that name), the page swaps in a generic
  "couldn't complete that — try again or contact support" message.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from urllib.parse import urlencode

import structlog
from bss_orchestrator.chat_caps import check_caps, record_chat_turn
from bss_orchestrator.customer_chat_prompt import (
    build_balance_summary,
    build_customer_chat_prompt,
)
from bss_orchestrator.session import (
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventTurnUsage,
    astream_once,
)
from bss_portal_ui.agent_log import render_html
from bss_portal_ui.sse import format_frame as _sse_frame
from bss_portal_ui.sse import status_html as _status_html
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..clients import get_clients
from ..security import requires_linked_customer
from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


# Generic message rendered when the trip-wire fires. Per the phase
# doc trap section: never leak detail. The customer sees the same
# string for any ownership violation; ops investigate via the audit
# row that ``record_violation`` wrote on the actor's record.
_OWNERSHIP_VIOLATION_REPLY = (
    "Sorry — I couldn't complete that. Please try again, or contact "
    "support if the issue persists."
)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    session: str | None = None,
    cap_tripped: str | None = None,
    retry_at: str | None = None,
    customer_id: str = Depends(requires_linked_customer),
) -> HTMLResponse:
    """The chat page. Renders three states inline:

    * Default — empty form ready for the customer's question.
    * ``?session=<sid>`` — opens an SSE stream to /chat/events/{sid}
      and renders the user's question + a streaming agent log.
    * ``?cap_tripped=<reason>`` — renders the templated cap banner
      with retry guidance; the form is hidden.
    """
    turn = None
    if session:
        store = request.app.state.chat_turn_store
        turn = await store.get(session)
        if turn is None or turn.customer_id != customer_id:
            # Stale session id or someone else's — fall back to empty
            # state. Cross-customer impersonation via crafted session
            # url is blocked here on the route side; the SSE handler
            # also re-checks.
            turn = None
            session = None

    return templates.TemplateResponse(
        request,
        "chat_page.html",
        {
            "customer_id": customer_id,
            "session_id": session,
            "turn": turn,
            "cap_tripped": cap_tripped,
            "retry_at": retry_at,
        },
    )


@router.post("/chat/message")
async def chat_message(
    request: Request,
    message: str = Form(...),
    customer_id: str = Depends(requires_linked_customer),
) -> RedirectResponse:
    """Handle a chat submission. Cap-check first; if blocked, redirect
    to the chat page with the cap-tripped banner. Otherwise create the
    turn and redirect to the SSE-connected chat page.

    Doctrine: cap-trip → templated response; never invoke the LLM.
    """
    text = message.strip()
    if not text:
        return RedirectResponse(url="/chat", status_code=303)

    status = await check_caps(customer_id)
    if not status.allowed:
        params: dict[str, str] = {"cap_tripped": status.reason or "cap_check_failed"}
        if status.retry_at is not None:
            params["retry_at"] = status.retry_at.isoformat()
        log.info(
            "chat.cap_tripped",
            customer_id=customer_id,
            reason=status.reason,
        )
        return RedirectResponse(
            url=f"/chat?{urlencode(params)}", status_code=303
        )

    store = request.app.state.chat_turn_store
    turn = await store.create(customer_id=customer_id, question=text)
    return RedirectResponse(
        url=f"/chat?session={turn.session_id}", status_code=303
    )


@router.get("/chat/events/{session_id}")
async def chat_events(
    request: Request,
    session_id: str,
    customer_id: str = Depends(requires_linked_customer),
) -> StreamingResponse:
    """SSE stream of agent events for one chat turn."""
    store = request.app.state.chat_turn_store
    turn = await store.get(session_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="chat turn not found")
    # Defence-in-depth — even if the URL was crafted, only the owning
    # customer can stream this turn. The trip-wire would also catch
    # any leaked-output bug, but blocking at the route is cheaper.
    if turn.customer_id != customer_id:
        log.warning(
            "chat.cross_customer_session_attempt",
            actor=customer_id,
            session_id=session_id,
            owner=turn.customer_id,
        )
        raise HTTPException(status_code=403, detail="not your chat session")

    # Build the customer-chat system prompt for this session. The
    # subscription read is best-effort — if it fails the prompt
    # renders ``(loading)`` placeholders rather than crashing the
    # stream. Prompt build runs once per turn (5-10s LLM dwarfs it).
    clients = get_clients()
    customer_dict: dict = {}
    primary_sub: dict | None = None
    customer_email = ""
    customer_name = ""
    plan_id = "(loading)"
    try:
        customer_dict = await clients.crm.get_customer(customer_id)
        customer_email = (
            customer_dict.get("email")
            or customer_dict.get("primaryEmail")
            or ""
        )
        customer_name = (
            customer_dict.get("name")
            or customer_dict.get("givenName")
            or "there"
        )
        subs = await clients.subscription.list_for_customer(customer_id)
        primary_sub = next(
            (s for s in subs if s.get("state") in {"active", "blocked"}),
            subs[0] if subs else None,
        )
        if primary_sub:
            plan_id = primary_sub.get("offeringId") or plan_id
    except Exception as exc:  # noqa: BLE001 — best-effort prompt build
        log.warning(
            "chat.prompt_context_load_failed",
            customer_id=customer_id,
            error=str(exc),
        )

    system_prompt = build_customer_chat_prompt(
        customer_name=customer_name,
        customer_email=customer_email,
        account_state=customer_dict.get("status", "active"),
        current_plan=plan_id,
        balance_summary=build_balance_summary(primary_sub),
    )

    transcript = f"User: {turn.question}\n"

    async def stream() -> AsyncIterator[bytes]:
        if turn.done:
            yield _sse_frame("status", _status_html("done"))
            return

        yield _sse_frame("status", _status_html("live"))

        try:
            async for event in astream_once(
                turn.question,
                allow_destructive=True,
                channel="portal-chat",
                actor=customer_id,
                service_identity="portal_self_serve",
                tool_filter="customer_self_serve",
                system_prompt=system_prompt,
                transcript=transcript,
            ):
                # Token-usage event is housekeeping only — record cost
                # and don't render it to the chat log.
                if isinstance(event, AgentEventTurnUsage):
                    try:
                        await record_chat_turn(
                            customer_id=customer_id,
                            prompt_tok=event.prompt_tok,
                            completion_tok=event.completion_tok,
                            model=event.model or None,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "chat.cost_record_failed",
                            customer_id=customer_id,
                            error=str(exc),
                        )
                    continue

                # Trip-wire surfaces as an AgentEventError with
                # ``AgentOwnershipViolation`` in the message — render
                # the generic safety reply instead of leaking the
                # name of the offending tool to the customer.
                if isinstance(event, AgentEventError) and (
                    "AgentOwnershipViolation" in event.message
                ):
                    turn.ownership_violation = True
                    turn.error = "ownership_violation"
                    turn.final_text = _OWNERSHIP_VIOLATION_REPLY
                    yield _sse_frame(
                        "message",
                        _safety_reply_html(_OWNERSHIP_VIOLATION_REPLY),
                    )
                    yield _sse_frame("status", _status_html("error"))
                    return

                if isinstance(event, AgentEventError):
                    turn.error = event.message
                    yield _sse_frame("message", render_html(event))
                    yield _sse_frame("status", _status_html("error"))
                    return

                try:
                    yield _sse_frame("message", render_html(event))
                except Exception as render_exc:  # noqa: BLE001
                    log.warning(
                        "chat.render_failed",
                        error=str(render_exc),
                        event_kind=type(event).__name__,
                    )
                    continue

                if isinstance(event, AgentEventFinalMessage):
                    # v0.12 — TurnUsage was already consumed above
                    # (astream_once yields it BEFORE FinalMessage so
                    # cost accounting lands before the SSE consumer
                    # disconnects on "done"). FinalMessage is the
                    # last frame the route emits.
                    turn.done = True
                    turn.final_text = event.text or ""
                    yield _sse_frame("status", _status_html("done"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("chat.stream_crashed")
            turn.error = f"{type(exc).__name__}: {exc}"
            yield _sse_frame("status", _status_html("error"))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _safety_reply_html(text: str) -> str:
    """Render the ownership-violation safety reply as a chat-log
    fragment matching the agent_event partial's row shape."""
    import html as _html

    return (
        '<div class="chat-event chat-event-error">'
        f'<span class="icon">⚠</span>'
        f'<span class="title">{_html.escape(text)}</span>'
        "</div>"
    )
