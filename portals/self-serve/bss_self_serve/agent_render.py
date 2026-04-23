"""Render ``AgentEvent`` objects to the HTML partials the SSE stream emits.

Every SSE frame is a pre-rendered HTML fragment (per V0_4_0.md §4 —
"Send HTML partials. The browser swaps them into the DOM via HTMX
with zero JavaScript"). This module owns that rendering and also
harvests domain IDs (CUST-nnn, ORD-nnn, SUB-nnn, eSIM activation
code) from tool results so the confirmation page can redirect the
user to the right subscription without re-asking the LLM.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from bss_orchestrator.session import (
    AgentEvent,
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventPromptReceived,
    AgentEventToolCallCompleted,
    AgentEventToolCallStarted,
)

from .templating import templates

_DETAIL_MAX = 80


@dataclass
class RenderedEvent:
    """An ``AgentEvent`` projected to the shape ``agent_event.html`` expects."""

    kind: str
    icon: str
    title: str
    detail: str = ""
    detail_full: str = ""
    is_error: bool = False


def project(event: AgentEvent) -> RenderedEvent:
    """Turn one typed event into a template context dict."""
    if isinstance(event, AgentEventPromptReceived):
        return RenderedEvent(
            kind="prompt",
            icon="→",
            title="prompt received",
            detail=_truncate(event.prompt),
            detail_full=event.prompt,
        )
    if isinstance(event, AgentEventToolCallStarted):
        args_str = _fmt_args(event.args)
        return RenderedEvent(
            kind="tool_started",
            icon="↳",
            title=f"{event.name}({args_str})" if args_str else f"{event.name}()",
            detail="",
            detail_full=_fmt_args_full(event.args),
        )
    if isinstance(event, AgentEventToolCallCompleted):
        return RenderedEvent(
            kind="tool_completed",
            icon="⚠" if event.is_error else "←",
            title=event.name,
            detail=_truncate(event.result),
            detail_full=event.result,
            is_error=event.is_error,
        )
    if isinstance(event, AgentEventFinalMessage):
        return RenderedEvent(
            kind="final",
            icon="✓",
            title="complete",
            detail=_truncate(event.text) if event.text else "",
            detail_full=event.text,
        )
    if isinstance(event, AgentEventError):
        return RenderedEvent(
            kind="error",
            icon="⚠",
            title="agent error",
            detail=event.message,
            is_error=True,
        )
    raise TypeError(f"Unknown AgentEvent variant: {type(event).__name__}")


def render_html(event: AgentEvent) -> str:
    """Render the partial for one event as a single-line HTML string.

    Newlines are collapsed so the string fits in a single ``data:``
    line of an SSE frame.
    """
    projected = project(event)
    html_frag = templates.get_template("partials/agent_event.html").render(
        event=projected.__dict__
    )
    return _collapse_lines(html_frag)


# ─────────────────────────────────────────────────────────────────────────────
# ID harvesting — read tool results and stash IDs on the session.
# ─────────────────────────────────────────────────────────────────────────────

_CUST_RE = re.compile(r"CUST-\d+")
_ORD_RE = re.compile(r"ORD-\d+")
_SUB_RE = re.compile(r"SUB-\d+")
_LPA_RE = re.compile(r"LPA:[^ \"'\n]+")


def harvest_ids(result_text: str) -> dict[str, str]:
    """Return whichever IDs appear in a tool result (empty dict if none)."""
    found: dict[str, str] = {}
    if m := _CUST_RE.search(result_text):
        found["customer_id"] = m.group(0)
    if m := _ORD_RE.search(result_text):
        found["order_id"] = m.group(0)
    if m := _SUB_RE.search(result_text):
        found["subscription_id"] = m.group(0)
    if m := _LPA_RE.search(result_text):
        found["activation_code"] = m.group(0)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int = _DETAIL_MAX) -> str:
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _fmt_args(args: dict) -> str:
    """Compact single-line arg summary, truncated for the row title."""
    if not args:
        return ""
    pairs = []
    for k, v in args.items():
        pairs.append(f"{k}={_short_repr(v)}")
    return _truncate(", ".join(pairs))


def _fmt_args_full(args: dict) -> str:
    """Full-fidelity arg repr for the hover tooltip."""
    try:
        return json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(args)


def _short_repr(value: object) -> str:
    if isinstance(value, str):
        if len(value) > 24:
            return f'"{value[:21]}…"'
        return f'"{value}"'
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    return _truncate(repr(value), 24)


def _collapse_lines(text: str) -> str:
    """SSE frames need one logical line per ``data:`` prefix."""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _sse_escape(text: str) -> str:
    """Escape a value for inclusion in an HTML attribute (test-support)."""
    return html.escape(text, quote=True)
