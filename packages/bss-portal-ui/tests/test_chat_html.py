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


# ── v0.13.1 extended block-level: tables, headings, ol, code fences ──


def test_pipe_table_renders_as_html_table() -> None:
    md = (
        "| Plan | Price | Data |\n"
        "|------|-------|------|\n"
        "| PLAN_S | $5 | 1 GB |\n"
        "| PLAN_M | $10 | 5 GB |\n"
    )
    out = render_chat_markdown(md)
    assert "<table" in out
    assert "<thead>" in out and "<th>Plan</th>" in out
    assert "<tbody>" in out
    assert "<td>PLAN_S</td>" in out and "<td>$5</td>" in out
    # Pipes shouldn't leak as literal characters.
    assert "| Plan |" not in out


def test_table_separator_with_alignment_markers() -> None:
    md = (
        "| Col | Right |\n"
        "|:----|------:|\n"
        "| a | b |\n"
    )
    out = render_chat_markdown(md)
    assert "<table" in out
    assert "<th>Col</th>" in out
    assert "<td>a</td>" in out


def test_table_with_inline_markdown_in_cells() -> None:
    md = (
        "| Plan | Notes |\n"
        "|------|-------|\n"
        "| **PLAN_S** | uses `5 GB` |\n"
    )
    out = render_chat_markdown(md)
    assert "<strong>PLAN_S</strong>" in out
    assert "<code>5 GB</code>" in out


def test_heading_renders_h3_minimum() -> None:
    out = render_chat_markdown("# Top heading")
    assert "<h3>Top heading</h3>" in out
    out2 = render_chat_markdown("### Smaller heading")
    assert "<h5>Smaller heading</h5>" in out2


def test_numbered_list_renders_ol() -> None:
    md = "1. first\n2. second\n3. third"
    out = render_chat_markdown(md)
    assert out.count("<li>") == 3
    assert "<ol>" in out
    assert "<ul>" not in out


def test_code_fence_renders_pre_block() -> None:
    md = "```\nfoo bar\nbaz\n```"
    out = render_chat_markdown(md)
    assert "<pre><code>foo bar\nbaz</code></pre>" in out


def test_code_fence_inside_does_not_render_inner_markdown() -> None:
    md = "```\n**not bold**\n```"
    out = render_chat_markdown(md)
    # Inside the fence, markdown is preserved literally (HTML-escaped).
    assert "<pre><code>**not bold**</code></pre>" in out


def test_unclosed_code_fence_doesnt_swallow_subsequent_blocks() -> None:
    """Defensive — a stray ```\\n at the end shouldn't crash. We close
    the pre block at end-of-text."""
    md = "```\nstuff\nmore stuff"
    out = render_chat_markdown(md)
    assert "<pre><code>stuff\nmore stuff</code></pre>" in out


def test_separator_row_alone_is_treated_as_paragraph() -> None:
    """A standalone ``|----|`` line without a preceding header is just
    text — no table emitted."""
    md = "|----|"
    out = render_chat_markdown(md)
    assert "<table" not in out


def test_assistant_bubble_strips_inner_newlines_for_sse() -> None:
    """SSE data: must be one line; tables embed newlines in the
    rendered HTML for human readability. The bubble wrapper strips
    them at the wire layer."""
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    bubble = render_assistant_bubble(md)
    assert "\n" not in bubble


# ── v0.13.1 — gemma reasoning-leakage stripping ──────────────────────


def test_strip_leading_thought_header() -> None:
    """Bare ``thought\\n\\nAnswer.`` shape — gemma's reasoning channel
    leaking into the regular content channel."""
    from bss_portal_ui import strip_reasoning_leakage

    out = strip_reasoning_leakage("thought\n\nThe answer is 42.")
    assert out == "The answer is 42."


def test_strip_think_xml_block() -> None:
    """``<think>...</think>`` block style — strip the whole block."""
    from bss_portal_ui import strip_reasoning_leakage

    out = strip_reasoning_leakage(
        "<think>weighing options...</think>\nThe answer is 42."
    )
    assert "weighing" not in out
    assert "The answer is 42." in out


def test_strip_does_not_touch_normal_text() -> None:
    from bss_portal_ui import strip_reasoning_leakage

    out = strip_reasoning_leakage("Plain reply with no leakage.")
    assert out == "Plain reply with no leakage."


# ── v0.19 — Rich/box-drawing ASCII panel preservation ───────────────


def test_ascii_panel_renders_inside_pre_block() -> None:
    """Rich Panel/Table output uses U+250x box-drawing characters. When
    the LLM regurgitates that ASCII art verbatim, a proportional-font
    chat bubble destroys alignment. Detect the run and emit <pre>."""
    md = (
        "Here you go:\n"
        "┌─ VAS Offerings ─────────────────────────┐\n"
        "│ ID            Name           Price       │\n"
        "│ VAS_DATA_1GB  Data Top-Up    3.00 SGD    │\n"
        "└──────────────────────────────────────────┘"
    )
    out = render_chat_markdown(md)
    assert "<pre><code>" in out
    # Box characters preserved literally (HTML escape doesn't touch them).
    assert "┌─ VAS Offerings" in out
    assert "└─" in out
    # Surrounding prose still rendered as a paragraph.
    assert "<p>Here you go:</p>" in out


def test_ascii_panel_pipe_borders_also_pre() -> None:
    """Some Rich themes render side borders as ASCII `|`. The detector
    fires on inner box-drawing chars too, so a fully-pipe-bordered
    panel that contains `─` separators still ends up in <pre>."""
    md = (
        "│ Status: ACTIVE │\n"
        "│ Type: Bundle   │\n"
        "│ ──── Allowances ──── │\n"
        "│ Data: 1024 MB  │"
    )
    out = render_chat_markdown(md)
    assert "<pre><code>" in out
    assert "Status: ACTIVE" in out


def test_renderer_strips_thought_before_render() -> None:
    """Integration: the bubble renderer chain strips the leakage as
    part of render_chat_markdown — so neither the SSE frame nor the
    persisted conversation row carries the gemma-style "thought"
    prefix."""
    bubble = render_assistant_bubble("thought\n\nHello, world.")
    assert "thought" not in bubble.lower()
    assert "Hello, world." in bubble
