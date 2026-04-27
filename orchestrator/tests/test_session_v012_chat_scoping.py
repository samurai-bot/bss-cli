"""astream_once chat-scoping wiring (v0.12 PR2).

Asserts the new ``tool_filter`` + ``system_prompt`` + ``actor`` parameters
on ``astream_once`` propagate to ``build_graph`` and that the
orchestrator-side auth_context is set for the duration of the stream.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from bss_orchestrator import auth_context
from bss_orchestrator.session import astream_once


class _FakeGraph:
    def __init__(self, updates: list[dict[str, Any]]):
        self._updates = updates

    async def astream(
        self, _input: Any, *, stream_mode: str = "updates"
    ) -> AsyncIterator[dict[str, Any]]:
        for u in self._updates:
            yield u


async def _collect(stream) -> list:
    return [ev async for ev in stream]


async def test_tool_filter_passed_to_build_graph() -> None:
    fake = _FakeGraph([{"agent": {"messages": [AIMessage(content="hi")]}}])
    captured: dict[str, Any] = {}

    def _fake_build_graph(**kwargs: Any) -> _FakeGraph:
        captured.update(kwargs)
        return fake

    with patch("bss_orchestrator.session.build_graph", side_effect=_fake_build_graph):
        await _collect(
            astream_once(
                "ping",
                channel="portal-self-serve",
                actor="CUST-042",
                tool_filter="customer_self_serve",
            )
        )

    assert captured.get("tool_filter") == "customer_self_serve"


async def test_system_prompt_passed_to_build_graph() -> None:
    fake = _FakeGraph([{"agent": {"messages": [AIMessage(content="hi")]}}])
    captured: dict[str, Any] = {}

    def _fake_build_graph(**kwargs: Any) -> _FakeGraph:
        captured.update(kwargs)
        return fake

    with patch("bss_orchestrator.session.build_graph", side_effect=_fake_build_graph):
        await _collect(
            astream_once(
                "ping",
                actor="CUST-042",
                system_prompt="You are the customer-chat assistant for CUST-042.",
            )
        )

    assert captured.get("system_prompt") == (
        "You are the customer-chat assistant for CUST-042."
    )


async def test_auth_context_actor_set_during_stream_and_reset_after() -> None:
    seen_actors: list[str | None] = []

    class _ProbeGraph(_FakeGraph):
        async def astream(self, _input, *, stream_mode="updates"):  # type: ignore[no-untyped-def]
            seen_actors.append(auth_context.current().actor)
            for u in self._updates:
                yield u

    fake = _ProbeGraph([{"agent": {"messages": [AIMessage(content="hi")]}}])

    # Before the stream the actor is None.
    assert auth_context.current().actor is None
    with patch("bss_orchestrator.session.build_graph", return_value=fake):
        await _collect(astream_once("ping", actor="CUST-042"))

    # Inside the graph's astream the actor was bound.
    assert seen_actors == ["CUST-042"]
    # After the stream completes (or raises) the actor is cleared.
    assert auth_context.current().actor is None


async def test_auth_context_resets_even_on_error() -> None:
    class _BoomGraph(_FakeGraph):
        async def astream(self, _input, *, stream_mode="updates"):  # type: ignore[no-untyped-def]
            raise RuntimeError("graph blew up mid-stream")
            yield  # pragma: no cover — make this an async generator

    with patch("bss_orchestrator.session.build_graph", return_value=_BoomGraph([])):
        events = await _collect(astream_once("ping", actor="CUST-042"))

    # The astream consumed the error into an AgentEventError instead
    # of leaking the exception. Critically, the actor must still be
    # cleared from auth_context — finally-block discipline.
    assert auth_context.current().actor is None
    assert any(getattr(e, "message", "").startswith("RuntimeError") for e in events)


async def test_actor_omitted_keeps_auth_context_default() -> None:
    fake = _FakeGraph([{"agent": {"messages": [AIMessage(content="hi")]}}])

    assert auth_context.current().actor is None
    with patch("bss_orchestrator.session.build_graph", return_value=fake):
        await _collect(astream_once("ping"))
    # actor=None means the wrappers would refuse — confirms the seam
    # never silently inherits a stale actor from a prior stream.
    assert auth_context.current().actor is None
