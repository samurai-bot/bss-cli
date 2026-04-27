"""Customer chat surface (v0.12 PR7 + PR13 conversation memory + popup widget).

The only orchestrator-mediated route in the self-serve portal — every
other route writes directly via bss-clients per the v0.10 / v0.11
doctrine. The doctrine guard ``check-chat-only`` in the Makefile
asserts ``astream_once`` appears only here.

Routes:

* ``GET /chat`` — the standalone chat page (full window). Renders
  the running conversation if any.
* ``GET /chat/widget`` — the same UI as a fixed-position bottom-right
  popup partial. The body-level FAB in base.html loads this via
  ``hx-get`` so the customer can chat from any post-login page
  without navigating away.
* ``POST /chat/message`` — form submission. Cap-check, append the
  user's message to the conversation, create a turn, and either
  redirect (full-page form) or return an HTMX widget refresh
  partial that opens the SSE stream in place.
* ``POST /chat/reset`` — clear the running conversation. Returns a
  fresh widget partial when called via HTMX; otherwise 303 to /chat.
* ``GET /chat/events/{sid}`` — SSE stream. Reads turn + the
  customer's running conversation, runs astream_once with prior
  context inline, on FinalMessage appends the assistant reply to
  the conversation so the next turn sees it.

Doctrine: cap-trip → templated response, no LLM invocation.
``AgentOwnershipViolation`` → generic safety reply, no leaked detail.
``AgentEventTurnUsage`` → ``chat_caps.record_chat_turn`` (cost
accounting). ``AgentEventFinalMessage`` rendered in full — the
chat surface owns the user-visible reply, so unlike the agent-log
widget it does not truncate.
"""

from __future__ import annotations

import asyncio
import html as _html
from collections.abc import AsyncIterator
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
    AgentEventToolCallStarted,
    AgentEventTurnUsage,
    astream_once,
)
from bss_portal_ui.sse import format_frame as _sse_frame
from bss_portal_ui.sse import status_html as _status_html
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..clients import get_clients
from ..security import requires_linked_customer
from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


_OWNERSHIP_VIOLATION_REPLY = (
    "Sorry — I couldn't complete that. Please try again, or contact "
    "support if the issue persists."
)


# ── Helpers ──────────────────────────────────────────────────────────


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request", "").lower() == "true"


async def _load_customer_context(customer_id: str) -> dict:
    """Read customer + primary subscription for the system prompt.
    Best-effort: failures fall through to ``(loading)`` placeholders
    rather than blocking the chat turn."""
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
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "chat.prompt_context_load_failed",
            customer_id=customer_id,
            error=str(exc),
        )
    return {
        "customer_dict": customer_dict,
        "primary_sub": primary_sub,
        "customer_email": customer_email,
        "customer_name": customer_name,
        "plan_id": plan_id,
    }


def _render_widget_context(
    *,
    customer_id: str,
    conversation,
    session_id: str | None,
    cap_tripped: str | None,
    retry_at: str | None,
) -> dict:
    """Shared template context for both the standalone page and the
    popup widget. The widget partial and the page template both pull
    from this so the layout stays in sync."""
    messages = []
    if conversation is not None:
        for m in conversation.messages:
            messages.append({"role": m.role, "body": m.body})
    return {
        "customer_id": customer_id,
        "session_id": session_id,
        "messages": messages,
        "has_history": bool(messages),
        "cap_tripped": cap_tripped,
        "retry_at": retry_at,
    }


# ── Routes ───────────────────────────────────────────────────────────


async def _resolve_session(
    request: Request, session: str | None, customer_id: str
) -> str | None:
    """Validate ``?session=<sid>`` against the turn store. Returns
    the id when valid + owned by the actor, otherwise ``None`` so
    the template skips the SSE host. Cross-customer impersonation
    via a crafted URL is blocked here (the SSE handler enforces too)."""
    if not session:
        return None
    turn = await request.app.state.chat_turn_store.get(session)
    if turn is None or turn.customer_id != customer_id:
        return None
    return session


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    cap_tripped: str | None = None,
    retry_at: str | None = None,
    session: str | None = None,
    customer_id: str = Depends(requires_linked_customer),
) -> HTMLResponse:
    """Standalone chat page. Always shows the running conversation
    plus the input form. ``?session=<sid>`` activates the SSE stream
    for an in-flight turn so the assistant's reply lands as it arrives."""
    conv = await request.app.state.chat_conversation_store.get(customer_id)
    valid_session = await _resolve_session(request, session, customer_id)
    return templates.TemplateResponse(
        request,
        "chat_page.html",
        _render_widget_context(
            customer_id=customer_id,
            conversation=conv,
            session_id=valid_session,
            cap_tripped=cap_tripped,
            retry_at=retry_at,
        ),
    )


@router.get("/chat/widget", response_class=HTMLResponse)
async def chat_widget(
    request: Request,
    session: str | None = None,
    cap_tripped: str | None = None,
    retry_at: str | None = None,
    customer_id: str = Depends(requires_linked_customer),
) -> HTMLResponse:
    """The popup widget partial. Loaded by the FAB's ``hx-get``
    into the ``#chat-widget-host`` div on every post-login page.
    Same context as the standalone page; the partial decides the
    fixed-position bottom-right styling."""
    conv = await request.app.state.chat_conversation_store.get(customer_id)
    valid_session = await _resolve_session(request, session, customer_id)
    return templates.TemplateResponse(
        request,
        "chat_widget.html",
        _render_widget_context(
            customer_id=customer_id,
            conversation=conv,
            session_id=valid_session,
            cap_tripped=cap_tripped,
            retry_at=retry_at,
        ),
    )


@router.post("/chat/message")
async def chat_message(
    request: Request,
    message: str = Form(...),
    customer_id: str = Depends(requires_linked_customer),
):
    """Append the user's message to the conversation and either
    redirect (full-page) or return a widget refresh (HTMX) so the
    SSE stream picks up the new turn."""
    text = message.strip()
    if not text:
        if _is_htmx(request):
            return await chat_widget(request, customer_id=customer_id)
        return RedirectResponse(url="/chat", status_code=303)

    cap = await check_caps(customer_id)
    if not cap.allowed:
        params: dict[str, str] = {"cap_tripped": cap.reason or "cap_check_failed"}
        if cap.retry_at is not None:
            params["retry_at"] = cap.retry_at.isoformat()
        log.info(
            "chat.cap_tripped",
            customer_id=customer_id,
            reason=cap.reason,
        )
        if _is_htmx(request):
            return await chat_widget(
                request,
                customer_id=customer_id,
                cap_tripped=cap.reason or "cap_check_failed",
                retry_at=cap.retry_at.isoformat() if cap.retry_at else None,
            )
        return RedirectResponse(
            url=f"/chat?{urlencode(params)}", status_code=303
        )

    conv_store = request.app.state.chat_conversation_store
    conv = await conv_store.get_or_create(customer_id)
    conv.append("user", text)

    turn_store = request.app.state.chat_turn_store
    turn = await turn_store.create(customer_id=customer_id, question=text)

    if _is_htmx(request):
        # Widget refresh: render the partial with the new
        # session_id so the SSE-bound elements are present in the
        # swap response.
        return await chat_widget(
            request, session=turn.session_id, customer_id=customer_id
        )
    return RedirectResponse(
        url=f"/chat?session={turn.session_id}", status_code=303
    )


@router.post("/chat/reset")
async def chat_reset(
    request: Request,
    customer_id: str = Depends(requires_linked_customer),
):
    """Clear the running conversation. The next message starts a
    fresh history — no prior context."""
    await request.app.state.chat_conversation_store.reset(customer_id)
    if _is_htmx(request):
        return await chat_widget(request, customer_id=customer_id)
    return RedirectResponse(url="/chat", status_code=303)


@router.get("/chat/events/{session_id}")
async def chat_events(
    request: Request,
    session_id: str,
    customer_id: str = Depends(requires_linked_customer),
) -> StreamingResponse:
    """SSE stream for one in-flight chat turn.

    The customer's running conversation is loaded so prior
    user/assistant turns appear as inline context in the system
    prompt — the LLM answers the *next* user message in continuity.
    On FinalMessage, the assistant's full reply is appended to the
    conversation so subsequent turns see it.
    """
    turn_store = request.app.state.chat_turn_store
    turn = await turn_store.get(session_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="chat turn not found")
    if turn.customer_id != customer_id:
        log.warning(
            "chat.cross_customer_session_attempt",
            actor=customer_id,
            session_id=session_id,
            owner=turn.customer_id,
        )
        raise HTTPException(status_code=403, detail="not your chat session")

    conv_store = request.app.state.chat_conversation_store
    conv = await conv_store.get_or_create(customer_id)

    ctx = await _load_customer_context(customer_id)
    primary_sub = ctx["primary_sub"]

    # Prior messages = everything in the conversation EXCEPT the
    # latest user message (the one this turn is answering — the
    # LLM sees it as ``prompt``, not as prior context).
    prior_pairs: list[tuple[str, str]] = [
        (m.role, m.body)
        for m in conv.messages
        if not (m.role == "user" and m.body == turn.question)
    ]

    system_prompt = build_customer_chat_prompt(
        customer_name=ctx["customer_name"],
        customer_email=ctx["customer_email"],
        account_state=ctx["customer_dict"].get("status", "active"),
        current_plan=ctx["plan_id"],
        balance_summary=build_balance_summary(primary_sub),
        prior_messages=prior_pairs,
    )

    # Transcript for case.open_for_me — full running text, including
    # the latest user message.
    transcript = conv.transcript_text()

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
                # Token-usage: record cost; don't render.
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

                # Trip-wire — generic safety reply, never leaked detail.
                if isinstance(event, AgentEventError) and (
                    "AgentOwnershipViolation" in event.message
                ):
                    turn.ownership_violation = True
                    turn.error = "ownership_violation"
                    turn.final_text = _OWNERSHIP_VIOLATION_REPLY
                    conv.append("assistant", _OWNERSHIP_VIOLATION_REPLY)
                    yield _sse_frame(
                        "message",
                        _chat_assistant_html(_OWNERSHIP_VIOLATION_REPLY, error=True),
                    )
                    yield _sse_frame("status", _status_html("error"))
                    return

                if isinstance(event, AgentEventError):
                    turn.error = event.message
                    fallback = "Sorry — something went wrong. Please try again."
                    conv.append("assistant", fallback)
                    yield _sse_frame(
                        "message", _chat_assistant_html(fallback, error=True)
                    )
                    yield _sse_frame("status", _status_html("error"))
                    return

                # Tool calls render as small inline pills so the
                # customer can see what the agent is doing.
                if isinstance(event, AgentEventToolCallStarted):
                    yield _sse_frame(
                        "message", _chat_tool_pill_html(event.name)
                    )
                    continue

                if isinstance(event, AgentEventFinalMessage):
                    text = event.text or ""
                    turn.done = True
                    turn.final_text = text
                    conv.append("assistant", text)
                    yield _sse_frame(
                        "message", _chat_assistant_html(text)
                    )
                    yield _sse_frame("status", _status_html("done"))
                    return

                # Everything else (intermediate AIMessages without
                # tool_calls, ToolMessage results) is hidden from the
                # chat log — the audit row + bss trace carry the
                # forensic record.
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


# ── Inline HTML renderers (chat-flavoured, not agent-log shaped) ─────


def _chat_assistant_html(text: str, *, error: bool = False) -> str:
    """Full assistant reply as a chat bubble. Newlines preserved
    via ``white-space: pre-wrap`` on the .chat-bubble class."""
    css = "chat-bubble chat-bubble-assistant"
    if error:
        css += " chat-bubble-error"
    safe = _html.escape(text)
    safe = safe.replace("\n", "<br>")
    return f'<div class="{css}">{safe}</div>'


def _chat_tool_pill_html(tool_name: str) -> str:
    return (
        '<div class="chat-tool-pill">'
        f'<span class="chat-tool-icon">≈</span>'
        f'<span class="chat-tool-name">{_html.escape(tool_name)}</span>'
        "</div>"
    )
