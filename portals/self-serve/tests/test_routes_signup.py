"""Signup route — form render, POST creates session + redirect, progress shell."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def test_signup_form_renders_plan_details_and_kyc_badge(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/signup/PLAN_M?msisdn=90000042")
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


def test_signup_form_without_msisdn_query_param_422s(authed_client):  # type: ignore[no-untyped-def]
    # Direct hit on /signup/{plan} without choosing a number first is a
    # programmer / scraper error; the form has nothing to render.
    resp = authed_client.get("/signup/PLAN_M")
    assert resp.status_code == 422


def test_signup_form_does_not_ask_for_email_again(authed_client):  # type: ignore[no-untyped-def]
    """v0.8: signup-form must read the email from the verified session
    instead of letting the visitor type it again. Letting it be
    re-entered creates a CRM customer with a different address than
    the linked identity — silent data divergence between
    portal_auth.identity and crm.contact_medium.
    """
    resp = authed_client.get("/signup/PLAN_M?msisdn=90000042")
    assert resp.status_code == 200
    body = resp.text
    # No email input on the form.
    assert 'name="email"' not in body
    assert 'type="email"' not in body
    # The verified email is shown as a read-only banner instead.
    assert "Signed in as" in body
    assert "ada@example.sg" in body  # matches authed_client's seeded identity


def test_signup_post_uses_session_email_not_form_email(authed_client):  # type: ignore[no-untyped-def]
    """Even if a form-side email is submitted (e.g. by a hand-crafted
    POST), the route must use identity.email from the verified session.
    """
    resp = authed_client.post(
        "/signup",
        data={
            "plan": "PLAN_M",
            "name": "Ada",
            # Hostile / outdated client tries to forge a different email.
            "email": "evil@attacker.example",
            "phone": "+6590001234",
            "msisdn": "90000042",
            "card_pan": "4242424242424242",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    session_id = parse_qs(urlparse(resp.headers["location"]).query)["session"][0]

    import asyncio
    store = authed_client.app.state.session_store
    sig = asyncio.run(store.get(session_id))
    assert sig is not None
    # The in-memory signup session must carry the verified-session email,
    # not the attacker-supplied one. Downstream agent uses sig.email.
    assert sig.email == "ada@example.sg"
    assert sig.email != "evil@attacker.example"


def test_signup_form_agent_log_is_idle_before_submit(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/signup/PLAN_M?msisdn=90000042")
    assert "Agent Activity" in resp.text
    assert "Submit the form to watch it work" in resp.text
    assert "sse-connect" not in resp.text


def test_signup_unknown_plan_returns_404(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/signup/PLAN_NOPE?msisdn=90000042")
    assert resp.status_code == 404


def test_signup_post_creates_session_and_redirects(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.post(
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
    store = authed_client.app.state.session_store
    sig = asyncio.run(store.get(session_id))
    assert sig.msisdn == "90000042"

    progress = authed_client.get(location)
    assert progress.status_code == 200
    assert session_id in progress.text
    assert f'sse-connect="/agent/events/{session_id}"' in progress.text


def test_signup_progress_with_unknown_session_404s(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/signup/PLAN_M/progress?session=unknown")
    assert resp.status_code == 404
