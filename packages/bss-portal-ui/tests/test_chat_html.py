"""Unit tests for bss_portal_ui.chat_html (v0.13 PR5).

These helpers were extracted from the v0.12 customer chat route so
the v0.13 operator cockpit thread renders identically. Tests cover
the security-critical behaviour first (HTML escaping is hostile-by-
default), then the markdown shape, then the bubble + pill wrappers.
"""

from __future__ import annotations

from bss_portal_ui import (
    render_assistant_bubble,
    render_chat_markdown,
    render_tool_pill,
)


# ── Security: hostile input must not leak raw HTML ───────────────────


def test_html_in_assistant_text_is_escaped() -> None:
    out = render_chat_markdown("<script>alert('x')</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_attribute_injection_attempt_is_escaped() -> None:
    out = render_chat_markdown('"><img src=x onerror=alert(1)>')
    assert "<img" not in out
    assert "onerror" in out  # the literal text is escaped, not stripped
    assert "&lt;img" in out


def test_tool_pill_escapes_name() -> None:
    out = render_tool_pill("<script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# ── Markdown shape ───────────────────────────────────────────────────


def test_bold_renders() -> None:
    out = render_chat_markdown("hello **world**")
    assert "<strong>world</strong>" in out


def test_italic_with_asterisks() -> None:
    out = render_chat_markdown("look *here*")
    assert "<em>here</em>" in out


def test_italic_with_underscores() -> None:
    out = render_chat_markdown("look _here_")
    assert "<em>here</em>" in out


def test_code_span_wraps_inner_inline_substitutions() -> None:
    """Pre-existing renderer behaviour (lifted from v0.12 chat.py
    unchanged): code spans wrap their content in <code>, but inline
    bold/italic substitutions still run on the inner text. We do
    NOT regress this — the customer chat surface relies on the
    existing shape; if the cockpit thread wants stricter behaviour,
    add a separate renderer."""
    out = render_chat_markdown("`**bold inside**`")
    assert "<code>" in out and "</code>" in out
    assert "<strong>bold inside</strong>" in out


def test_unordered_list_renders() -> None:
    md = "- one\n- two\n- three"
    out = render_chat_markdown(md)
    assert out.count("<li>") == 3
    assert "<ul>" in out


def test_paragraphs_separate_on_blank_line() -> None:
    md = "first.\n\nsecond."
    out = render_chat_markdown(md)
    assert out.count("<p>") == 2


def test_empty_text_renders_nbsp() -> None:
    assert render_chat_markdown("") == "&nbsp;"
    assert render_chat_markdown(None) == "&nbsp;"  # type: ignore[arg-type]


def test_no_link_or_image_pass_through() -> None:
    """We render no markdown links or images on purpose — XSS surface."""
    out = render_chat_markdown("[click](javascript:alert(1))")
    assert "<a" not in out
    out2 = render_chat_markdown("![alt](http://example.com/img.png)")
    assert "<img" not in out2


# ── Bubble + pill wrappers ───────────────────────────────────────────


def test_assistant_bubble_carries_default_class() -> None:
    out = render_assistant_bubble("hi")
    assert 'class="chat-bubble chat-bubble-assistant"' in out
    assert "<p>hi</p>" in out


def test_assistant_bubble_carries_error_modifier() -> None:
    out = render_assistant_bubble("nope", error=True)
    assert "chat-bubble-error" in out


def test_tool_pill_shape() -> None:
    out = render_tool_pill("subscription.terminate")
    assert 'class="chat-tool-pill"' in out
    assert "subscription.terminate" in out
    assert "≈" in out  # pill icon
