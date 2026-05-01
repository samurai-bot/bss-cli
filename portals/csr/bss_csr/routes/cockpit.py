"""Operator cockpit — browser veneer over the v0.13 Conversation store.

Mirrors the CLI REPL. Both surfaces read and write the same Postgres-
backed cockpit.session/message/pending_destructive tables; exit ``bss``,
open ``/cockpit/<id>``, see the same turns. Per phases/V0_13_0.md
§3.2:

    GET  /                              → sessions index
    GET  /cockpit/{session_id}          → chat thread page
    POST /cockpit/{session_id}/turn     → enqueue a user message
    GET  /cockpit/{session_id}/events   → SSE stream
    POST /cockpit/{session_id}/reset    → conversation.reset()
    POST /cockpit/{session_id}/confirm  → flip next turn destructive
    POST /cockpit/{session_id}/focus    → set/clear customer focus
    POST /cockpit/new                   → 303 → /cockpit/<new id>
    GET  /case/{id}                     → kept (read-only deep link)

No login route. No middleware-level auth. The cockpit runs single-
operator-by-design behind a secure perimeter; ``actor`` comes from
``.bss-cli/settings.toml`` via ``bss_cockpit.config.current()``.

Doctrine: this is the only orchestrator-mediated route in the CSR
portal. Doctrine guard ``rg 'astream_once' portals/csr/bss_csr/routes/``
must match cockpit.py only.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import structlog
from bss_clients.errors import ClientError
from bss_cockpit import (
    Conversation,
    build_cockpit_prompt,
    current as cockpit_config_current,
)
from bss_orchestrator.clients import get_clients
from bss_orchestrator.session import (
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventToolCallStarted,
    astream_once,
)
from bss_portal_ui import (
    render_assistant_bubble,
    render_tool_pill,
)
from bss_portal_ui.sse import format_frame as _sse_frame
from bss_portal_ui.sse import status_html as _status_html
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Destructive-tool prefixes (mirrors cli/bss_cli/repl.py) ──────────


_DESTRUCTIVE_PREFIXES = (
    "subscription.terminate",
    "subscription.migrate_to_new_price",
    "subscription.purchase_vas",
    "subscription.schedule_plan_change",
    "subscription.cancel_pending_plan_change",
    "payment.add_card",
    "payment.remove_method",
    "payment.charge",
    "customer.create",
    "customer.update_contact",
    "customer.attest_kyc",
    "customer.close",
    "customer.add_contact_medium",
    "customer.remove_contact_medium",
    "case.open",
    "case.close",
    "case.add_note",
    "case.transition",
    "case.update_priority",
    "ticket.open",
    "ticket.assign",
    "ticket.transition",
    "ticket.resolve",
    "ticket.close",
    "ticket.cancel",
    "order.create",
    "order.cancel",
    "catalog.add_offering",
    "catalog.add_price",
    "catalog.window_offering",
    "provisioning.resolve_stuck",
    "provisioning.retry_failed",
    "provisioning.set_fault_injection",
)


def _is_destructive(tool_name: str) -> bool:
    return any(
        tool_name == p or tool_name.startswith(p) for p in _DESTRUCTIVE_PREFIXES
    )


def _operator_actor() -> str:
    """``actor`` for cockpit turns. Source-of-truth is settings.toml."""
    return cockpit_config_current().settings.operator.actor


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Sessions index — the operator's recent cockpit sessions."""
    cfg = cockpit_config_current()
    actor = cfg.settings.operator.actor
    rows = await Conversation.list_for(actor)
    return templates.TemplateResponse(
        request,
        "sessions_index.html",
        {
            "actor": actor,
            "model": cfg.settings.llm.model or "(env default)",
            "sessions": rows,
        },
    )


@router.post("/cockpit/new")
async def new_session(request: Request) -> RedirectResponse:
    """Open a fresh cockpit session and 303 to it."""
    actor = _operator_actor()
    label = (await request.form()).get("label", "") or None
    conv = await Conversation.open(actor=actor, label=label)
    return RedirectResponse(url=f"/cockpit/{conv.session_id}", status_code=303)


@router.get("/cockpit/{session_id}", response_class=HTMLResponse)
async def cockpit_thread(
    request: Request, session_id: str
) -> HTMLResponse:
    """Chat-thread page. Renders prior messages + an input form."""
    try:
        conv = await Conversation.resume(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    transcript = await conv.transcript_text()
    cfg = cockpit_config_current()
    return templates.TemplateResponse(
        request,
        "cockpit_thread.html",
        {
            "actor": cfg.settings.operator.actor,
            "model": cfg.settings.llm.model or "(env default)",
            "conversation": conv,
            "transcript_blocks": _split_transcript_blocks(transcript),
            "stream_session_id": request.query_params.get("turn", ""),
        },
    )


def _split_transcript_blocks(transcript: str) -> list[dict[str, str]]:
    """Parse ``role:\\ncontent`` blocks for template rendering.

    Mirrors the role mapping the orchestrator uses (user / assistant /
    tool[NAME]). Tool blocks carry the bracketed name so the template
    can render them with a different visual treatment than assistant
    bubbles.
    """
    out: list[dict[str, str]] = []
    if not transcript.strip():
        return out
    for block in transcript.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, body = block.partition("\n")
        head = head.strip().rstrip(":")
        body = body.strip()
        if not head:
            continue
        if head.startswith("tool"):
            tool_name = ""
            if head.startswith("tool[") and head.endswith("]"):
                tool_name = head[len("tool["):-1]
            out.append({"role": "tool", "tool_name": tool_name, "body": body})
        elif head in {"user", "assistant"}:
            out.append({"role": head, "tool_name": "", "body": body})
    return out


@router.post("/cockpit/{session_id}/turn")
async def cockpit_turn(
    request: Request,
    session_id: str,
    message: str = Form(...),
) -> RedirectResponse:
    """Append the user message and 303 back so the SSE stream picks it up.

    The session_id query param signals the thread template to attach an
    ``hx-ext="sse"`` connection to ``/cockpit/<id>/events`` for the
    next render.
    """
    try:
        conv = await Conversation.resume(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    text = message.strip()
    if not text:
        return RedirectResponse(
            url=f"/cockpit/{session_id}", status_code=303
        )
    await conv.append_user_turn(text)
    # The events endpoint reads the latest user message off the
    # conversation row; no separate turn store needed.
    return RedirectResponse(
        url=f"/cockpit/{session_id}?turn=1", status_code=303
    )


@router.post("/cockpit/{session_id}/reset")
async def cockpit_reset(session_id: str) -> RedirectResponse:
    try:
        conv = await Conversation.resume(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await conv.reset()
    return RedirectResponse(url=f"/cockpit/{session_id}", status_code=303)


@router.post("/cockpit/{session_id}/confirm")
async def cockpit_confirm(session_id: str) -> RedirectResponse:
    """No-op except as a marker. The next turn's SSE handler consumes
    any pending_destructive row; this POST exists so the browser has a
    button to press, parity with the REPL's /confirm slash command."""
    try:
        await Conversation.resume(session_id)  # 404 if missing
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=f"/cockpit/{session_id}", status_code=303)


@router.post("/cockpit/{session_id}/focus")
async def cockpit_focus(
    session_id: str,
    customer_id: str = Form(default=""),
) -> RedirectResponse:
    try:
        conv = await Conversation.resume(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await conv.set_focus(customer_id.strip() or None)
    return RedirectResponse(url=f"/cockpit/{session_id}", status_code=303)


# ── SSE turn stream ──────────────────────────────────────────────────


@router.get("/cockpit/{session_id}/events")
async def cockpit_events(
    request: Request, session_id: str
) -> StreamingResponse:
    """Drive one cockpit turn through astream_once and yield SSE frames.

    The latest user message on the conversation is the prompt; prior
    turns become transcript context. On AgentEventToolCallStarted, a
    tool-pill frame is emitted; on FinalMessage, the assistant bubble
    is rendered. Pending-destructive proposals captured during the
    stream are stashed via Conversation.set_pending_destructive so the
    next /confirm-bracketed turn can authorise the call.
    """
    try:
        conv = await Conversation.resume(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    cfg = cockpit_config_current()
    actor = cfg.settings.operator.actor

    # Pull the latest user message off the conversation. Bail cleanly
    # if there isn't one (page reload after the turn already streamed).
    transcript = await conv.transcript_text()
    blocks = _split_transcript_blocks(transcript)
    last_user_index: int | None = None
    for i, b in enumerate(blocks):
        if b["role"] == "user":
            last_user_index = i
    if last_user_index is None:
        async def empty():  # noqa: ANN202
            yield _sse_frame("status", _status_html("done"))
        return StreamingResponse(
            empty(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Skip if this user message has already been answered (an assistant
    # turn after it). Page reloads thus don't re-run the LLM.
    answered_after = any(
        blocks[j]["role"] == "assistant" for j in range(last_user_index + 1, len(blocks))
    )
    if answered_after:
        async def replay():  # noqa: ANN202
            yield _sse_frame("status", _status_html("done"))
        return StreamingResponse(
            replay(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    user_message = blocks[last_user_index]["body"]

    # Consume any pending_destructive row so build_cockpit_prompt can
    # surface the confirmed-action block.
    pending = await conv.consume_pending_destructive()
    allow_destructive_this_turn = pending is not None

    # Transcript fed into the LLM = everything BEFORE the new user
    # message. The user message itself becomes the prompt.
    prior_blocks = blocks[:last_user_index]
    prior_transcript = _join_blocks(prior_blocks)
    system_prompt = build_cockpit_prompt(
        operator_md=cfg.operator_md,
        customer_focus=conv.customer_focus,
        pending_destructive=pending,
        extra_context={
            "model": cfg.settings.llm.model or "(env default)",
            "session_id": conv.session_id,
        },
    )

    captured_tool_calls: list[dict[str, Any]] = []
    last_proposal: tuple[str, dict] | None = None

    async def stream() -> AsyncIterator[bytes]:
        nonlocal last_proposal
        yield _sse_frame("status", _status_html("live"))
        try:
            async for event in astream_once(
                user_message,
                allow_destructive=allow_destructive_this_turn,
                channel="portal-csr",
                actor=actor,
                service_identity="operator_cockpit",
                tool_filter="operator_cockpit",
                system_prompt=system_prompt,
                transcript=prior_transcript,
            ):
                if isinstance(event, AgentEventToolCallStarted):
                    captured_tool_calls.append(
                        {"name": event.name, "args": event.args}
                    )
                    if not allow_destructive_this_turn and _is_destructive(
                        event.name
                    ):
                        last_proposal = (event.name, event.args)
                    yield _sse_frame(
                        "message", render_tool_pill(event.name)
                    )
                    continue
                if isinstance(event, AgentEventError):
                    text = "Sorry — something went wrong. Please try again."
                    await conv.append_assistant_turn(
                        text, tool_calls_json=captured_tool_calls or None
                    )
                    yield _sse_frame(
                        "message", render_assistant_bubble(text, error=True)
                    )
                    yield _sse_frame("status", _status_html("error"))
                    return
                if isinstance(event, AgentEventFinalMessage):
                    text = event.text or "(no reply)"
                    asst_id = await conv.append_assistant_turn(
                        text, tool_calls_json=captured_tool_calls or None
                    )
                    if last_proposal is not None and not allow_destructive_this_turn:
                        tn, ta = last_proposal
                        await conv.set_pending_destructive(
                            tool_name=tn,
                            args=ta,
                            proposal_message_id=asst_id,
                        )
                    yield _sse_frame(
                        "message", render_assistant_bubble(text)
                    )
                    yield _sse_frame("status", _status_html("done"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("cockpit.stream_crashed")
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


def _join_blocks(blocks: list[dict[str, str]]) -> str:
    """Inverse of ``_split_transcript_blocks`` — render back to the canonical
    ``role:\\ncontent\\n\\nrole:\\ncontent`` form."""
    parts: list[str] = []
    for b in blocks:
        if b["role"] == "tool":
            head = (
                f"tool[{b['tool_name']}]" if b["tool_name"] else "tool"
            )
        else:
            head = b["role"]
        parts.append(f"{head}:\n{b['body']}")
    return "\n\n".join(parts)
