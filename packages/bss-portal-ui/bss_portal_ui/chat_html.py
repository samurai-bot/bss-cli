"""Chat-bubble HTML renderers shared by the customer-chat surface (v0.12)
and the operator-cockpit chat thread (v0.13).

Both surfaces stream the same shape — assistant-bubble + tool-call pill —
through SSE. v0.12 originated these helpers in
``portals/self-serve/.../routes/chat.py``; v0.13 lifts them here so the
cockpit thread renders identically without copy-paste drift.

Doctrine: the LLM's output is hostile-by-default. We HTML-escape every
character first, then convert a small whitelisted set of markdown tokens
(``**bold**``, ``*italic*``, ``_italic_``, `` `code` ``, ``- list`` /
``* list``, paragraph breaks) into HTML. No raw-HTML pass-through; no
link/image rendering — those would invite XSS via crafted prompt-injection
responses. Same shape on both surfaces; same security boundary.
"""

from __future__ import annotations

import html as _html
import re as _re

__all__ = [
    "render_assistant_bubble",
    "render_tool_pill",
    "render_chat_markdown",
]


_RE_BOLD = _re.compile(r"\*\*(?P<inner>[^*\n]+)\*\*")
_RE_ITALIC_AST = _re.compile(r"(?<!\*)\*(?P<inner>[^*\n]+)\*(?!\*)")
_RE_ITALIC_UND = _re.compile(r"(?<!\w)_(?P<inner>[^_\n]+)_(?!\w)")
_RE_CODE = _re.compile(r"`(?P<inner>[^`\n]+)`")
_RE_LIST_ITEM = _re.compile(r"^\s*[\*\-]\s+(?P<body>.*)$")


def _render_inline(line: str) -> str:
    """Apply inline markdown to a single, already-HTML-escaped line.

    Order matters: code spans first (they shadow ``*`` etc.); bold
    before italic so ``**`` doesn't get partially-eaten.
    """
    out = _RE_CODE.sub(lambda m: f"<code>{m.group('inner')}</code>", line)
    out = _RE_BOLD.sub(lambda m: f"<strong>{m.group('inner')}</strong>", out)
    out = _RE_ITALIC_AST.sub(lambda m: f"<em>{m.group('inner')}</em>", out)
    out = _RE_ITALIC_UND.sub(lambda m: f"<em>{m.group('inner')}</em>", out)
    return out


def render_chat_markdown(text: str) -> str:
    """Block-level + inline markdown render for assistant chat output.

    HTML-escapes the whole text once up front, then walks lines grouping
    list runs and paragraphs. Returns a single-line HTML string suitable
    for the ``data:`` field of an SSE frame (no embedded newlines after
    the join).
    """
    escaped = _html.escape(text or "")
    lines = escaped.split("\n")

    out: list[str] = []
    para: list[str] = []
    list_items: list[str] = []

    def _flush_list() -> None:
        if list_items:
            out.append(
                "<ul>"
                + "".join(f"<li>{_render_inline(it)}</li>" for it in list_items)
                + "</ul>"
            )
            list_items.clear()

    def _flush_para() -> None:
        if para:
            joined = "<br>".join(_render_inline(p) for p in para)
            out.append(f"<p>{joined}</p>")
            para.clear()

    for raw in lines:
        line = raw.rstrip()
        item_match = _RE_LIST_ITEM.match(line)
        if item_match:
            _flush_para()
            list_items.append(item_match.group("body"))
            continue
        if not line.strip():
            # blank line — paragraph / list break
            _flush_list()
            _flush_para()
            continue
        _flush_list()
        para.append(line)

    _flush_list()
    _flush_para()
    return "".join(out) or "&nbsp;"


def render_assistant_bubble(text: str, *, error: bool = False) -> str:
    """Full assistant reply as a chat bubble. Single-line HTML for SSE.

    Adds ``chat-bubble-error`` modifier when ``error=True`` so portal
    CSS can dim or red-tint a fallback / ownership-violation reply.
    """
    css = "chat-bubble chat-bubble-assistant"
    if error:
        css += " chat-bubble-error"
    return f'<div class="{css}">{render_chat_markdown(text)}</div>'


def render_tool_pill(tool_name: str) -> str:
    """Inline pill announcing a tool call to the human reader.

    Renders identically on the customer chat surface and the operator
    cockpit thread. The tool name is HTML-escaped — even though
    registered tool names follow a known shape, the renderer treats
    inputs as untrusted.
    """
    return (
        '<div class="chat-tool-pill">'
        '<span class="chat-tool-icon">≈</span>'
        f'<span class="chat-tool-name">{_html.escape(tool_name)}</span>'
        "</div>"
    )
