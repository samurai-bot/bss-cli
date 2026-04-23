"""Tests for ``Session.astream`` — v0.6 streaming variant of ``Session.ask``.

Mirrors the test_session_streaming.py coverage of ``astream_once`` but
asserts the per-session history-keeping behaviour the REPL relies on.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bss_orchestrator.session import (
    AgentEventFinalMessage,
    AgentEventPromptReceived,
    AgentEventToolCallCompleted,
    AgentEventToolCallStarted,
    Session,
)


class _FakeGraph:
    def __init__(self, updates: list[dict[str, Any]]):
        self._updates = updates

    async def astream(self, _input, *, stream_mode="updates"):  # type: ignore[no-untyped-def]
        for u in self._updates:
            yield u


def _new_session(updates: list[dict[str, Any]]) -> Session:
    with patch("bss_orchestrator.session.build_graph", return_value=_FakeGraph(updates)):
        return Session()


async def _collect(s, text: str) -> list:
    return [ev async for ev in s.astream(text)]


async def test_astream_yields_prompt_then_final_for_text_only_reply() -> None:
    s = _new_session([
        {"agent": {"messages": [AIMessage(content="hello there")]}},
    ])
    events = await _collect(s, "say hi")
    assert isinstance(events[0], AgentEventPromptReceived)
    assert events[0].prompt == "say hi"
    assert isinstance(events[-1], AgentEventFinalMessage)
    assert events[-1].text == "hello there"


async def test_astream_emits_tool_call_started_then_completed_pair() -> None:
    s = _new_session([
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "c1", "name": "subscription.get", "args": {"id": "SUB-1"}},
                        ],
                    )
                ]
            }
        },
        {
            "tools": {
                "messages": [
                    ToolMessage(
                        content='{"id": "SUB-1", "state": "active"}',
                        name="subscription.get",
                        tool_call_id="c1",
                    )
                ]
            }
        },
        {"agent": {"messages": [AIMessage(content="Subscription is active.")]}},
    ])
    events = await _collect(s, "show me sub")
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "AgentEventPromptReceived",
        "AgentEventToolCallStarted",
        "AgentEventToolCallCompleted",
        "AgentEventFinalMessage",
    ]
    assert events[1].name == "subscription.get"
    assert events[1].args == {"id": "SUB-1"}
    assert events[2].result.startswith('{"id": "SUB-1"')
    assert events[3].text == "Subscription is active."


async def test_astream_appends_human_message_to_history() -> None:
    s = _new_session([
        {"agent": {"messages": [AIMessage(content="ok")]}},
    ])
    await _collect(s, "first turn")
    # Human message + AI message both land in history.
    assert any(
        isinstance(m, HumanMessage) and m.content == "first turn" for m in s.history
    )
    assert any(isinstance(m, AIMessage) for m in s.history)


async def test_astream_history_persists_across_two_turns() -> None:
    # First turn — fake graph yields one AI message.
    fake1 = _FakeGraph([
        {"agent": {"messages": [AIMessage(content="reply 1")]}},
    ])
    with patch("bss_orchestrator.session.build_graph", return_value=fake1):
        s = Session()
    await _collect(s, "turn 1")
    history_after_turn1 = list(s.history)

    # Swap the cached graph for the second turn and verify history grows.
    s._graph = _FakeGraph([
        {"agent": {"messages": [AIMessage(content="reply 2")]}},
    ])
    await _collect(s, "turn 2")
    assert len(s.history) > len(history_after_turn1)
    assert any(
        isinstance(m, HumanMessage) and m.content == "turn 2" for m in s.history
    )


async def test_astream_dedupes_repeated_tool_call_ids() -> None:
    s = _new_session([
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "dup", "name": "x", "args": {}}],
                    )
                ]
            }
        },
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "dup", "name": "x", "args": {}}],
                    )
                ]
            }
        },
        {"agent": {"messages": [AIMessage(content="done")]}},
    ])
    events = await _collect(s, "do it")
    started = [e for e in events if isinstance(e, AgentEventToolCallStarted)]
    assert len(started) == 1
