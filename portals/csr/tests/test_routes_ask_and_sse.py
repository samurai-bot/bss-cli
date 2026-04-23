"""POST /customer/{id}/ask + SSE stream + auto-refresh trigger."""

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

from bss_csr.config import Settings
from bss_csr.main import create_app
from conftest import (  # type: ignore[import-not-found]
    FakeBundle,
    sample_customer,
    sample_subscription,
)


def _parse_sse(text: str) -> list[tuple[str, str]]:
    frames: list[tuple[str, str]] = []
    event_name = "message"
    data: list[str] = []
    for line in text.splitlines():
        if line == "":
            if data:
                frames.append((event_name, "\n".join(data)))
            event_name = "message"
            data = []
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].lstrip())
    if data:
        frames.append((event_name, "\n".join(data)))
    return frames


@pytest.fixture
def authed_client_with_agent(fake_clients: FakeBundle):
    """TestClient with a logged-in operator + canned agent stream."""
    fake_clients.crm.customers_by_id["CUST-test01"] = sample_customer()
    fake_clients.subscription.by_customer["CUST-test01"] = [{"id": "SUB-007"}]
    fake_clients.subscription.by_id["SUB-007"] = sample_subscription()

    canned = [
        AgentEventPromptReceived(prompt="(operator asked something)"),
        AgentEventToolCallStarted(name="subscription.get", args={}, call_id="c1"),
        AgentEventToolCallCompleted(
            name="subscription.get", call_id="c1", result='{"state": "blocked"}'
        ),
        AgentEventToolCallStarted(name="catalog.list_vas", args={}, call_id="c2"),
        AgentEventToolCallCompleted(
            name="catalog.list_vas", call_id="c2", result="[VAS_DATA_5GB]"
        ),
        AgentEventToolCallStarted(
            name="subscription.purchase_vas",
            args={"subscription_id": "SUB-007"},
            call_id="c3",
        ),
        AgentEventToolCallCompleted(
            name="subscription.purchase_vas",
            call_id="c3",
            result='{"state": "active"}',
        ),
        AgentEventFinalMessage(text="Topped up 5GB. Subscription active again."),
    ]

    captured: dict = {}

    async def fake_ask_about_customer(
        *, customer_id: str, question: str, operator_id: str
    ) -> AsyncIterator:  # type: ignore[no-untyped-def]
        captured["customer_id"] = customer_id
        captured["question"] = question
        captured["operator_id"] = operator_id
        for e in canned:
            yield e

    with patch("bss_csr.routes.search.get_clients", return_value=fake_clients), \
         patch("bss_csr.routes.customer.get_clients", return_value=fake_clients), \
         patch("bss_csr.routes.agent_events.ask_about_customer", new=fake_ask_about_customer):
        app = create_app(Settings())
        with TestClient(app) as c:
            login = c.post(
                "/login", data={"username": "csr-demo-001"}, follow_redirects=False
            )
            assert login.status_code == 303
            yield c, captured


def test_ask_creates_agent_session_and_redirects_to_360(authed_client_with_agent):  # type: ignore[no-untyped-def]
    client, _captured = authed_client_with_agent
    resp = client.post(
        "/customer/CUST-test01/ask",
        data={"question": "Why is their data not working?"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/customer/CUST-test01?session=")


def test_ask_endpoint_requires_login(client):  # type: ignore[no-untyped-def]
    resp = client.post(
        "/customer/CUST-test01/ask",
        data={"question": "anything"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_sse_stream_relays_agent_events_and_fires_agent_complete(
    authed_client_with_agent,
):  # type: ignore[no-untyped-def]
    client, captured = authed_client_with_agent
    sub = client.post(
        "/customer/CUST-test01/ask",
        data={"question": "Why is their data not working?"},
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]

    resp = client.get(f"/agent/events/{session_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(resp.text)
    event_names = [n for n, _ in frames]
    # status:live + 8 message frames + status:done + agent-complete
    assert event_names[0] == "status"
    assert event_names.count("message") == 8
    assert "agent-complete" in event_names
    assert event_names[-1] == "agent-complete"

    # Each message frame is an HTML <li>, not JSON.
    for name, data in frames:
        if name == "message":
            assert data.lstrip().startswith("<li")
            assert "agent-event" in data

    # The bridge received the operator + customer + question, untouched.
    assert captured["operator_id"] == "csr-demo-001"
    assert captured["customer_id"] == "CUST-test01"
    assert "data not working" in captured["question"]


def test_unknown_session_returns_404(authed_client_with_agent):  # type: ignore[no-untyped-def]
    client, _ = authed_client_with_agent
    resp = client.get("/agent/events/unknown")
    assert resp.status_code == 404


def test_done_session_replays_no_message_frames(authed_client_with_agent):  # type: ignore[no-untyped-def]
    client, _ = authed_client_with_agent
    sub = client.post(
        "/customer/CUST-test01/ask",
        data={"question": "Top up 5GB."},
        follow_redirects=False,
    )
    session_id = sub.headers["location"].split("session=")[-1]
    # Drive once to done.
    _ = client.get(f"/agent/events/{session_id}").text
    # Reconnect — should be a one-shot status, no message replay.
    resp = client.get(f"/agent/events/{session_id}")
    assert "event: message" not in resp.text
    assert "event: status" in resp.text


def test_customer_360_has_auto_refresh_triggers_on_session_pages(authed_client_with_agent):  # type: ignore[no-untyped-def]
    client, _ = authed_client_with_agent
    # Open the 360 with a session attached — body opens SSE,
    # 4 sections carry hx-trigger="sse:agent-complete from:body".
    resp = client.get("/customer/CUST-test01?session=anything-goes")
    body = resp.text
    assert 'sse-connect="/agent/events/anything-goes"' in body
    # Each auto-refresh section names its hx-trigger correctly.
    assert body.count("sse:agent-complete from:body") >= 3
