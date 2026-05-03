"""v0.16 stripe-mode signup tests — Track 2.

Verifies that flipping ``BSS_PAYMENT_PROVIDER=stripe`` mode-switches:

1. The initial /signup form (drops the card-number input; renders a
   "you'll add your card on the next page" hint instead).
2. The /signup/{plan} POST (accepts empty card_pan; doesn't reject as
   policy.payment.method.invalid_card the way mock-mode does).
3. The /signup/step/cof/mount endpoint (pivots state to
   pending_cof_elements).
4. The /signup/step/cof endpoint (accepts payment_method_id from form
   instead of running the local mock tokenizer; passes
   tokenization_provider='stripe' to the BSS payment service).

The post-login add-card flow at /payment-methods/add gets its own
template-routing test in test_pci_scope (which proves the production-
stripe deployment never carries a card_number input).
"""

from __future__ import annotations

import pytest

from bss_self_serve.session import SignupSession


def _make_stripe_app(authed_client):
    """Flip the live test app into stripe mode for one test.

    The authed_client fixture set payment_provider='mock' on app.state
    at lifespan startup. This helper toggles it (and stamps the
    publishable key) for a single test, then restores at teardown.
    """
    app = authed_client.app
    prev = (
        getattr(app.state, "payment_provider", "mock"),
        getattr(app.state, "payment_stripe_publishable_key", ""),
    )
    app.state.payment_provider = "stripe"
    app.state.payment_stripe_publishable_key = "pk_test_fake_for_unit_tests"
    return prev


def _restore_app(authed_client, prev):
    app = authed_client.app
    app.state.payment_provider, app.state.payment_stripe_publishable_key = prev


def test_signup_form_in_stripe_mode_omits_card_number_input(authed_client):
    prev = _make_stripe_app(authed_client)
    try:
        resp = authed_client.get("/signup/PLAN_M?msisdn=90000042")
        assert resp.status_code == 200
        body = resp.text
        # Stripe-mode form does NOT render the mock card-number input.
        assert 'name="card_number"' not in body
        assert "4242424242424242" not in body
        # AND it tells the customer the card step happens next.
        assert "secure Stripe form" in body or "next page" in body
        # The hidden card_pan field is still there to satisfy the POST
        # /signup form contract (route reads card_pan="" + skips the
        # not-empty check in stripe mode).
        assert 'name="card_pan"' in body
    finally:
        _restore_app(authed_client, prev)


def test_signup_post_in_stripe_mode_accepts_empty_card_pan(
    authed_client, fake_clients
):
    """Mock mode 422s on empty card_pan; stripe mode allows it
    because the card is collected at the COF step via Elements."""
    prev = _make_stripe_app(authed_client)
    try:
        resp = authed_client.post(
            "/signup",
            data={
                "plan": "PLAN_M",
                "name": "Stripe Test",
                "phone": "90000042",
                "msisdn": "90000042",
                "card_pan": "",  # empty — would 422 in mock mode
            },
            follow_redirects=False,
        )
        # Either 303 to /progress (success) or 422 with a different
        # reason (still not the missing-card-pan rule).
        if resp.status_code == 422:
            assert "policy.payment.method.invalid_card" not in resp.text
        else:
            assert resp.status_code in (302, 303)
            assert "/signup/PLAN_M/progress" in resp.headers.get("location", "")
    finally:
        _restore_app(authed_client, prev)


def test_cof_mount_pivots_state_to_pending_cof_elements(authed_client):
    """POST /signup/step/cof/mount transitions a pending_cof signup into
    pending_cof_elements without writing anything to the payment service.

    The pivot is server-side so the timeline label stays consistent and
    the Elements iframe is rendered with the publishable key from
    app.state, not the form.
    """
    prev = _make_stripe_app(authed_client)
    try:
        # Plant a pending_cof signup in the in-memory store.
        store = authed_client.app.state.session_store
        identity_id = authed_client.app.state.test_identity_id
        import asyncio

        async def _do() -> str:
            sig = await store.create(
                plan="PLAN_M",
                name="Stripe Test",
                email="stripetest@example.com",
                phone="90000042",
                msisdn="90000042",
                card_pan="",
                identity_id=identity_id,
            )
            sig.customer_id = "CUST-STRIPE-TEST"
            sig.step = "pending_cof"
            await store.update(sig)
            return sig.session_id

        sid = asyncio.run(_do())

        resp = authed_client.post(f"/signup/step/cof/mount?session={sid}")
        assert resp.status_code == 200, resp.text
        # Body should now render the Elements iframe.
        assert "stripe-card-element" in resp.text
        assert "pk_test_fake_for_unit_tests" in resp.text

        async def _read_state() -> str:
            sig = await store.get(sid)
            return sig.step

        assert asyncio.run(_read_state()) == "pending_cof_elements"
    finally:
        _restore_app(authed_client, prev)


def test_cof_post_with_payment_method_id_calls_payment_service_with_stripe_provider(
    authed_client, fake_clients
):
    """The stripe path on POST /signup/step/cof passes
    tokenization_provider='stripe' (instead of 'sandbox') to the BSS
    payment service, so the service's StripeTokenizerAdapter does the
    ensure_customer + attach round-trips."""
    prev = _make_stripe_app(authed_client)
    try:
        store = authed_client.app.state.session_store
        identity_id = authed_client.app.state.test_identity_id
        import asyncio

        async def _do() -> str:
            sig = await store.create(
                plan="PLAN_M",
                name="Stripe Test",
                email="stripetest@example.com",
                phone="90000042",
                msisdn="90000042",
                card_pan="",
                identity_id=identity_id,
            )
            sig.customer_id = "CUST-STRIPE-TEST"
            sig.step = "pending_cof_elements"
            await store.update(sig)
            return sig.session_id

        sid = asyncio.run(_do())

        # Stub the bss-clients PaymentClient to capture the call args.
        captured: dict = {}
        async def _fake_create_pm(**kwargs):
            captured.update(kwargs)
            return {"id": "PM-STRIPE-001"}
        fake_clients.payment.create_payment_method = _fake_create_pm

        resp = authed_client.post(
            f"/signup/step/cof?session={sid}",
            data={"payment_method_id": "pm_test_card_visa"},
        )
        assert resp.status_code == 200, resp.text

        assert captured.get("tokenization_provider") == "stripe"
        assert captured.get("card_token") == "pm_test_card_visa"
        assert captured.get("customer_id") == "CUST-STRIPE-TEST"
    finally:
        _restore_app(authed_client, prev)


def test_cof_post_with_empty_payment_method_id_pivots_to_elements(
    authed_client,
):
    """A poll-style POST /signup/step/cof in stripe mode without a
    pm_id pivots state to pending_cof_elements + re-renders the
    iframe — never calls the payment service."""
    prev = _make_stripe_app(authed_client)
    try:
        store = authed_client.app.state.session_store
        identity_id = authed_client.app.state.test_identity_id
        import asyncio

        async def _do() -> str:
            sig = await store.create(
                plan="PLAN_M",
                name="Stripe Test",
                email="stripetest@example.com",
                phone="90000042",
                msisdn="90000042",
                card_pan="",
                identity_id=identity_id,
            )
            sig.customer_id = "CUST-STRIPE-TEST"
            sig.step = "pending_cof"
            await store.update(sig)
            return sig.session_id

        sid = asyncio.run(_do())

        resp = authed_client.post(
            f"/signup/step/cof?session={sid}",
            data={"payment_method_id": ""},
        )
        assert resp.status_code == 200
        assert "stripe-card-element" in resp.text

        async def _read() -> str:
            sig = await store.get(sid)
            return sig.step

        assert asyncio.run(_read()) == "pending_cof_elements"
    finally:
        _restore_app(authed_client, prev)
