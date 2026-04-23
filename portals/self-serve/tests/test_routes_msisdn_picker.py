"""MSISDN picker — /signup/{plan}/msisdn"""

from __future__ import annotations


def test_picker_renders_available_numbers_as_plan_specific_links(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M/msisdn")
    assert resp.status_code == 200
    body = resp.text
    # Numbers the FakeInventory fixture marked as available appear.
    assert "9000 0002" in body  # display-formatted
    assert "90000002" in body   # raw, in the href
    assert 'href="/signup/PLAN_M?msisdn=90000002"' in body
    # The assigned one must NOT appear (status filter).
    assert "90000001" not in body


def test_picker_unknown_plan_404s(client):  # type: ignore[no-untyped-def]
    assert client.get("/signup/PLAN_NOPE/msisdn").status_code == 404


def test_picker_agent_log_is_idle(client):  # type: ignore[no-untyped-def]
    # Widget on every page, not streaming yet (no session_id).
    resp = client.get("/signup/PLAN_M/msisdn")
    assert "Agent Activity" in resp.text
    assert "sse-connect" not in resp.text


def test_picker_accepts_prefix_filter(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M/msisdn?prefix=90000010")
    body = resp.text
    assert "9000 0010" in body
    # Everything else filtered out by prefix.
    assert "9000 0002" not in body


def test_picker_rejects_non_digit_prefix(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M/msisdn?prefix=abc")
    assert resp.status_code == 422
