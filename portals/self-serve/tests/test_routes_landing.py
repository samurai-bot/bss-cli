"""Landing page renders plan cards from a mocked catalog client."""

from __future__ import annotations


def test_landing_returns_200_and_renders_three_plans(client):  # type: ignore[no-untyped-def]
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    for plan_id in ("PLAN_S", "PLAN_M", "PLAN_L"):
        assert plan_id in body
    # Plan names from the fixture
    for name in ("Sidekick", "Mainline", "Long Haul"):
        assert name in body


def test_landing_shows_the_agent_log_widget(client):  # type: ignore[no-untyped-def]
    resp = client.get("/")
    # The hero artifact must be visible on the landing page — per V0_4_0.md §5a
    assert "Agent Activity" in resp.text
    assert "agent-log-events" in resp.text


def test_landing_links_to_msisdn_picker_for_each_plan(client):  # type: ignore[no-untyped-def]
    resp = client.get("/")
    # Landing now sends users through the MSISDN picker first.
    for plan_id in ("PLAN_S", "PLAN_M", "PLAN_L"):
        assert f'href="/signup/{plan_id}/msisdn"' in resp.text
