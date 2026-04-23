"""Signup route — form render, POST creates session + redirect, progress shell."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def test_signup_form_renders_plan_details_and_kyc_badge(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M?msisdn=90000042")
    assert resp.status_code == 200
    body = resp.text
    assert "PLAN_M" in body
    assert "Mainline" in body
    # Chosen MSISDN threads through the form
    assert "90000042" in body
    assert "+65 9000 0042" in body  # display-formatted
    # Pre-baked KYC attestation — no file upload
    assert "KYC-PREBAKED-001" in body
    assert "Myinfo" in body
    # Mock tokenizer test card is the default
    assert "4242424242424242" in body


def test_signup_form_without_msisdn_query_param_422s(client):  # type: ignore[no-untyped-def]
    # Direct hit on /signup/{plan} without choosing a number first is a
    # programmer / scraper error; the form has nothing to render.
    resp = client.get("/signup/PLAN_M")
    assert resp.status_code == 422


def test_signup_form_agent_log_is_idle_before_submit(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M?msisdn=90000042")
    assert "Agent Activity" in resp.text
    assert "Submit the form to watch it work" in resp.text
    assert "sse-connect" not in resp.text


def test_signup_unknown_plan_returns_404(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_NOPE?msisdn=90000042")
    assert resp.status_code == 404


def test_signup_post_creates_session_and_redirects(client):  # type: ignore[no-untyped-def]
    resp = client.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ada Lovelace",
            "email": "ada@example.sg",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/signup/PLAN_M/progress?session=")
    session_id = parse_qs(urlparse(location).query)["session"][0]
    assert len(session_id) == 32

    # The chosen number stuck in the session.
    import asyncio
    store = client.app.state.session_store
    sig = asyncio.get_event_loop().run_until_complete(store.get(session_id))
    assert sig.msisdn == "90000042"

    progress = client.get(location)
    assert progress.status_code == 200
    assert session_id in progress.text
    assert f'sse-connect="/agent/events/{session_id}"' in progress.text


def test_signup_progress_with_unknown_session_404s(client):  # type: ignore[no-untyped-def]
    resp = client.get("/signup/PLAN_M/progress?session=unknown")
    assert resp.status_code == 404
