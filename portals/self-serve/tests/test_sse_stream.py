"""SSE endpoint — /agent/events/{session_id}.

Mocks agent_bridge.drive_signup at the route's use site so the test
never touches a real LLM or downstream service. Asserts the stream
emits well-formed text/event-stream frames carrying HTML partials
(not JSON) and populates the session with IDs harvested from tool
results.
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
from fastapi.testclient import TestClient

from bss_self_serve.config import Settings
from bss_self_serve.main import create_app


def _parse_sse(text: str) -> list[tuple[str, str]]:
    """Minimal SSE frame parser — returns [(event_name, data), ...]."""
    frames: list[tuple[str, str]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line == "":
            if data_lines:
                frames.append((event_name, "\n".join(data_lines)))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if data_lines:
        frames.append((event_name, "\n".join(data_lines)))
    return frames


@pytest.fixture
def client_with_agent_mock(fake_clients, authed_client):  # type: ignore[no-untyped-def]
    """TestClient with get_clients + agent_bridge.drive_signup patched.

    v0.8: piggybacks on the ``authed_client`` fixture so the signup
    POST passes ``Depends(requires_verified_email)``. The seeded
    identity_id flows through into the in-memory signup session, which
    in turn lets the agent_events stream call link_to_customer when a
    CUST-* id is harvested.
    """
    canned = [
        AgentEventPromptReceived(prompt="Create customer Ck on PLAN_M…"),
        AgentEventToolCallStarted(
            name="customer.create", args={"name": "Ck"}, call_id="c1"
        ),
        AgentEventToolCallCompleted(
            name="customer.create",
            call_id="c1",
            result='{"id": "CUST-042"}',
        ),
        AgentEventToolCallStarted(
            name="order.create", args={"offering_id": "PLAN_M"}, call_id="c2"
        ),
        AgentEventToolCallCompleted(
            name="order.create",
            call_id="c2",
            result='{"id": "ORD-014", "state": "acknowledged"}',
        ),
        AgentEventFinalMessage(
            text=(
                "Signup complete. Subscription SUB-007 is active on PLAN_M. "
                "Activation code LPA:1$smdp.bss-cli.local$abc-123-def."
            )
        ),
    ]

    async def fake_drive_signup(**_kwargs) -> AsyncIterator:  # type: ignore[no-untyped-def]
        for e in canned:
            yield e

    with patch("bss_self_serve.routes.agent_events.drive_signup", new=fake_drive_signup):
        yield authed_client


def test_unknown_session_returns_404(client_with_agent_mock):  # type: ignore[no-untyped-def]
    resp = client_with_agent_mock.get("/agent/events/unknown-session-id")
    assert resp.status_code == 404


def test_sse_stream_emits_expected_frames_for_full_signup(client_with_agent_mock):  # type: ignore[no-untyped-def]
    # Create a real session via POST /signup so the SSE route finds it.
    sub = client_with_agent_mock.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ck",
            "email": "ck@example.com",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    assert sub.status_code == 303
    session_id = sub.headers["location"].split("session=")[-1]

    resp = client_with_agent_mock.get(f"/agent/events/{session_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(resp.text)
    event_names = [name for name, _ in frames]

    # Opening status + one frame per canned event + closing status + redirect.
    assert event_names[0] == "status"  # live
    assert event_names.count("message") == 6
    assert "status" in event_names[-3:]  # done
    assert "redirect" in event_names

    message_frames = [data for name, data in frames if name == "message"]
    # Each message frame is an HTML <li> partial, not JSON.
    for frag in message_frames:
        assert frag.lstrip().startswith("<li")
        assert "agent-event" in frag

    # The sequence of event CSS classes mirrors the agent's flow.
    kinds_in_order = ["prompt", "tool_started", "tool_completed", "tool_started", "tool_completed", "final"]
    for expected, frame in zip(kinds_in_order, message_frames):
        assert f"agent-event--{expected}" in frame


def test_sse_stream_populates_session_with_harvested_ids(client_with_agent_mock):  # type: ignore[no-untyped-def]
    sub = client_with_agent_mock.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ck",
            "email": "ck@example.com",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]

    resp = client_with_agent_mock.get(f"/agent/events/{session_id}")
    assert resp.status_code == 200
    _ = resp.text  # drain the stream

    # Pull the session back via the portal's own GET /signup/{plan}/progress
    # route — which will 404 if the store lost it and 200 if the harvested
    # IDs are there. Harder-facing assertion: scrape the rendered HTML.
    store = client_with_agent_mock.app.state.session_store
    import asyncio
    sig = asyncio.run(store.get(session_id))
    assert sig is not None
    assert sig.customer_id == "CUST-042"
    assert sig.order_id == "ORD-014"
    assert sig.subscription_id == "SUB-007"
    assert sig.activation_code.startswith("LPA:1$")
    assert sig.done is True


def test_sse_stream_snapshots_event_log_on_session(client_with_agent_mock):  # type: ignore[no-untyped-def]
    sub = client_with_agent_mock.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ck",
            "email": "ck@example.com",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]
    resp = client_with_agent_mock.get(f"/agent/events/{session_id}")
    assert resp.status_code == 200
    _ = resp.text  # drain

    import asyncio
    store = client_with_agent_mock.app.state.session_store
    sig = asyncio.run(store.get(session_id))
    assert sig is not None
    kinds = [e["kind"] for e in sig.event_log]
    assert kinds == [
        "prompt",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "final",
    ]
    # Prompt detail is the FULL prompt, not truncated.
    prompt_entry = sig.event_log[0]
    assert prompt_entry["detail"] == prompt_entry["detail_full"]
    assert len(prompt_entry["detail"]) > 20  # canned stream uses a real sentence


def test_sse_stream_done_session_replays_no_message_frames(client_with_agent_mock):  # type: ignore[no-untyped-def]
    # Done sessions must NOT re-emit "complete" frames on every SSE
    # reconnect — that was the v0.4 regression where the confirmation
    # page spammed the widget.
    sub = client_with_agent_mock.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ck",
            "email": "ck@example.com",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]
    # First GET drives the agent to done.
    _ = client_with_agent_mock.get(f"/agent/events/{session_id}").text
    # Second GET simulates the browser's auto-reconnect — should have
    # zero ``event: message`` frames, just a one-shot status.
    resp = client_with_agent_mock.get(f"/agent/events/{session_id}")
    text = resp.text
    assert "event: message" not in text
    assert "event: status" in text


def test_sse_stream_redirect_event_carries_activation_url(client_with_agent_mock):  # type: ignore[no-untyped-def]
    sub = client_with_agent_mock.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ck",
            "email": "ck@example.com",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]

    resp = client_with_agent_mock.get(f"/agent/events/{session_id}")
    frames = _parse_sse(resp.text)
    redirect = next((d for name, d in frames if name == "redirect"), None)
    assert redirect is not None
    # After a successful signup the agent produces ORD-014; redirect
    # goes to /activation/{order_id} per agent_events._redirect_html.
    assert '/activation/ORD-014' in redirect
    assert f'session={session_id}' in redirect


