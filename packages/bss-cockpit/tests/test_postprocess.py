"""Unit tests for bss_cockpit.postprocess (v0.20.1).

Two helpers, both surface-agnostic:

* ``strip_channel_markup`` — removes Harmony / channel-format leakage
  (``<channel|>`` / ``<|channel|>`` / ``</channel>`` / leading
  ``assistantfinal``) so the REPL Panel and the browser bubble both
  start at the real content.
* ``knowledge_called`` — bool helper used by both surfaces to decide
  whether pipe-table rendering is legitimate this turn (renderer-less
  tool fired → prose IS the answer, tables are real; otherwise, pipes
  fall through as literal text per v0.19 doctrine).
"""

from __future__ import annotations

from bss_cockpit.postprocess import knowledge_called, strip_channel_markup


# ── strip_channel_markup ────────────────────────────────────────────


def test_strip_channel_markup_pipe_suffix_variant() -> None:
    """The most common shape — ``<channel|>`` at the very start of the
    bubble. gemma's final-message stream emits this when the model's
    response format isn't pinned by the gateway."""
    assert (
        strip_channel_markup("<channel|>To configure email...")
        == "To configure email..."
    )


def test_strip_channel_markup_bracketed_variant() -> None:
    """``<|channel|>`` — the fully-bracketed Harmony shape."""
    assert (
        strip_channel_markup("<|channel|>commentary text")
        == "commentary text"
    )


def test_strip_channel_markup_close_tag() -> None:
    """``</channel>`` close-side variant occasionally trails a bubble."""
    out = strip_channel_markup("answer text</channel>")
    assert "</channel>" not in out
    assert "answer text" in out


def test_strip_channel_markup_assistantfinal_marker() -> None:
    """Bare ``assistantfinal`` line at the start of the bubble — strip
    it but keep the body that follows."""
    out = strip_channel_markup("assistantfinal\nThe answer is 42.")
    assert "assistantfinal" not in out
    assert "The answer is 42." in out


def test_strip_channel_markup_case_insensitive() -> None:
    """Open-weight models occasionally upper-case the channel marker."""
    assert strip_channel_markup("<CHANNEL|>hi") == "hi"


def test_strip_channel_markup_idempotent() -> None:
    """Running the strip twice is a no-op once the markup is gone."""
    once = strip_channel_markup("<channel|>hello")
    twice = strip_channel_markup(once)
    assert once == twice == "hello"


def test_strip_channel_markup_no_artefacts_passes_through() -> None:
    """Plain text is untouched."""
    assert strip_channel_markup("Plain reply.") == "Plain reply."


def test_strip_channel_markup_empty_input() -> None:
    """Empty / None-ish inputs return unchanged so callers don't have
    to special-case them."""
    assert strip_channel_markup("") == ""


def test_strip_channel_markup_preserves_inner_pipes() -> None:
    """We only strip the markup TOKENS, not pipes that are part of the
    real content — pipe tables, Unix command lines, etc."""
    out = strip_channel_markup(
        "<channel|>Run `cat foo | grep bar` for the result."
    )
    assert "cat foo | grep bar" in out
    assert "<channel|>" not in out


# ── knowledge_called ────────────────────────────────────────────────


def test_knowledge_called_with_search_tool() -> None:
    """The most common case — ``knowledge.search`` fired this turn."""
    calls = [{"name": "knowledge.search", "args": {"q": "email config"}}]
    assert knowledge_called(calls) is True


def test_knowledge_called_with_get_tool() -> None:
    """``knowledge.get`` is the other surface; same carve-out."""
    calls = [{"name": "knowledge.get", "args": {"anchor": "x"}}]
    assert knowledge_called(calls) is True


def test_knowledge_called_with_other_tools_only() -> None:
    """Renderer-backed tools alone — no carve-out, tables stay literal."""
    calls = [
        {"name": "customer.get", "args": {}},
        {"name": "subscription.list_for_customer", "args": {}},
    ]
    assert knowledge_called(calls) is False


def test_knowledge_called_mixed_calls() -> None:
    """At least one ``knowledge.*`` flips the gate — even if other,
    renderer-backed tools also fired in the same turn."""
    calls = [
        {"name": "customer.get", "args": {}},
        {"name": "knowledge.search", "args": {"q": "..."}},
    ]
    assert knowledge_called(calls) is True


def test_knowledge_called_empty_list() -> None:
    """No tools fired (pure conversation) — pipes stay literal."""
    assert knowledge_called([]) is False


def test_knowledge_called_none_input() -> None:
    """``None`` is the legitimate ``captured_tool_calls`` shape when
    the cockpit hasn't tracked any calls yet — return False."""
    assert knowledge_called(None) is False


def test_knowledge_called_accepts_string_iterable() -> None:
    """Callers without args context can pass a plain list of names —
    the helper tolerates the simpler shape."""
    assert knowledge_called(["knowledge.search"]) is True
    assert knowledge_called(["customer.get", "order.list"]) is False


def test_knowledge_called_ignores_malformed_entries() -> None:
    """An entry without a string ``name`` is ignored, not crashed-on."""
    calls = [
        {"name": None, "args": {}},
        42,
        {"name": "knowledge.search"},
    ]
    assert knowledge_called(calls) is True
