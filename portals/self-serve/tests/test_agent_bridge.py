"""Agent bridge unit tests — no real orchestrator, no real LLM.

We patch ``bss_orchestrator.session.astream_once`` at its use site
inside ``agent_bridge`` and feed a canned event stream. This proves
the bridge wiring (prompt built correctly, pin on allow_destructive,
channel override) without spinning up the graph.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from bss_orchestrator.session import (
    AgentEventFinalMessage,
    AgentEventPromptReceived,
    AgentEventToolCallCompleted,
    AgentEventToolCallStarted,
)

from bss_self_serve import agent_bridge
from bss_self_serve.prompts import (
    KYC_PREBAKED_ATTESTATION_ID,
    KYC_PREBAKED_SIGNATURE,
    signup_prompt,
)


async def _canned_stream(*_args, **_kwargs) -> AsyncIterator:  # type: ignore[no-untyped-def]
    yield AgentEventPromptReceived(prompt="test")
    yield AgentEventToolCallStarted(name="customer.create", args={}, call_id="c1")
    yield AgentEventToolCallCompleted(name="customer.create", call_id="c1", result="CUST-042")
    yield AgentEventFinalMessage(text="ok")


@pytest.mark.asyncio
async def test_drive_signup_passes_channel_and_blocks_destructive() -> None:
    captured: dict[str, object] = {}

    async def spy(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["prompt"] = prompt
        captured.update(kwargs)
        async for event in _canned_stream():
            yield event

    with patch.object(agent_bridge, "astream_once", new=spy):
        events = [
            e
            async for e in agent_bridge.drive_signup(
                name="Ck",
                email="ck@example.com",
                phone="+6590009999",
                plan="PLAN_M",
                card_pan="4242424242424242",
            )
        ]

    assert captured["channel"] == "portal-self-serve"
    assert captured["allow_destructive"] is False
    assert len(events) == 4
    assert isinstance(events[0], AgentEventPromptReceived)
    assert isinstance(events[-1], AgentEventFinalMessage)


@pytest.mark.asyncio
async def test_drive_signup_relays_every_event_in_order() -> None:
    emitted = [
        AgentEventPromptReceived(prompt="p"),
        AgentEventToolCallStarted(name="a", args={}, call_id="1"),
        AgentEventToolCallCompleted(name="a", call_id="1", result="r1"),
        AgentEventToolCallStarted(name="b", args={}, call_id="2"),
        AgentEventToolCallCompleted(name="b", call_id="2", result="r2"),
        AgentEventFinalMessage(text="done"),
    ]

    async def emit(*_a, **_k):  # type: ignore[no-untyped-def]
        for event in emitted:
            yield event

    with patch.object(agent_bridge, "astream_once", new=emit):
        out = [
            e
            async for e in agent_bridge.drive_signup(
                name="X",
                email="x@y.z",
                phone="+0",
                plan="PLAN_S",
                card_pan="4242424242424242",
            )
        ]

    assert out == emitted


def test_signup_prompt_contains_all_form_fields_and_kyc_attestation() -> None:
    prompt = signup_prompt(
        name="Ada Lovelace",
        email="ada@bss-cli.local",
        phone="+6590001234",
        plan="PLAN_M",
        card_pan="4242424242424242",
    )
    assert "Ada Lovelace" in prompt
    assert "ada@bss-cli.local" in prompt
    assert "+6590001234" in prompt
    assert "PLAN_M" in prompt
    assert "4242424242424242" in prompt
    assert KYC_PREBAKED_SIGNATURE in prompt
    assert KYC_PREBAKED_ATTESTATION_ID in prompt
