"""Confirmation page — QR PNG + LPA code + plan summary."""

from __future__ import annotations


def _seed_session_and_subscription(client, fake_clients, *, with_activation_on_session=True):  # type: ignore[no-untyped-def]
    import asyncio
    store = client.app.state.session_store
    sig = asyncio.run(
        store.create(
            plan="PLAN_M",
            name="Ada",
            email="ada@example.sg",
            phone="+6590001234",
            msisdn="90000042",
            card_pan="4242424242424242",
        )
    )
    sig.subscription_id = "SUB-007"
    sig.order_id = "ORD-014"
    if with_activation_on_session:
        sig.activation_code = "LPA:1$smdp.bss-cli.local$abc-123-def"
    sig.done = True
    sig.event_log = [
        {
            "kind": "prompt",
            "icon": "→",
            "title": "prompt received",
            "detail": "Full prompt text: create customer Ada on PLAN_M with MSISDN 90000042…",
            "detail_full": "Full prompt text: create customer Ada on PLAN_M with MSISDN 90000042…",
            "is_error": False,
        },
        {
            "kind": "tool_started",
            "icon": "↳",
            "title": 'customer.create(name="Ada")',
            "detail": "",
            "detail_full": '{"name": "Ada"}',
            "is_error": False,
        },
        {
            "kind": "tool_completed",
            "icon": "←",
            "title": "customer.create",
            "detail": '{"id": "CUST-042"}',
            "detail_full": '{"id": "CUST-042", "href": "/tmf-api/customerManagement/v4/customer/CUST-042"}',
            "is_error": False,
        },
        {
            "kind": "final",
            "icon": "✓",
            "title": "complete",
            "detail": "Signup complete. SUB-007 active.",
            "detail_full": "Signup complete. SUB-007 active.",
            "is_error": False,
        },
    ]
    asyncio.run(store.update(sig))

    fake_clients.subscription.records["SUB-007"] = {
        "id": "SUB-007",
        "state": "active",
        "offeringId": "PLAN_M",
        "iccid": "8910101000000000001",
        "msisdn": "90000001",
    }
    return sig


def test_confirmation_shows_qr_lpa_and_plan(client, fake_clients):  # type: ignore[no-untyped-def]
    sig = _seed_session_and_subscription(client, fake_clients)
    resp = client.get(f"/confirmation/SUB-007?session={sig.session_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "SUB-007" in body
    assert "LPA:1$smdp.bss-cli.local$abc-123-def" in body
    # PNG QR embedded as a data URI
    assert 'src="data:image/png;base64,' in body
    # Plan details rendered from the catalog (20480 mb → 20 GB in fixture)
    assert "Mainline" in body
    assert "20 GB" in body


def test_confirmation_falls_back_to_inventory_when_session_missing_lpa(client, fake_clients):  # type: ignore[no-untyped-def]
    sig = _seed_session_and_subscription(client, fake_clients, with_activation_on_session=False)
    fake_clients.inventory.activations["8910101000000000001"] = {
        "iccid": "8910101000000000001",
        "activation_code": "LPA:1$smdp.bss-cli.local$fallback-xyz",
    }

    resp = client.get(f"/confirmation/SUB-007?session={sig.session_id}")
    assert resp.status_code == 200
    assert "LPA:1$smdp.bss-cli.local$fallback-xyz" in resp.text


def test_confirmation_unknown_session_404s(client, fake_clients):  # type: ignore[no-untyped-def]
    resp = client.get("/confirmation/SUB-007?session=unknown")
    assert resp.status_code == 404


def test_confirmation_agent_log_widget_is_present(client, fake_clients):  # type: ignore[no-untyped-def]
    sig = _seed_session_and_subscription(client, fake_clients)
    resp = client.get(f"/confirmation/SUB-007?session={sig.session_id}")
    assert "Agent Activity" in resp.text


def test_confirmation_replays_transcript_statically_without_sse(client, fake_clients):  # type: ignore[no-untyped-def]
    sig = _seed_session_and_subscription(client, fake_clients)
    resp = client.get(f"/confirmation/SUB-007?session={sig.session_id}")
    body = resp.text
    # No live SSE connection — would otherwise re-trigger the agent
    # and spam the widget with "complete" frames on every reconnect.
    assert "sse-connect" not in body
    assert "sse-swap" not in body
    # Each event from the session's event_log rendered on the page.
    assert "prompt received" in body
    assert 'customer.create(name=&#34;Ada&#34;)' in body
    assert "CUST-042" in body
    # Header reflects the done status, not "live".
    assert 'class="dot done"' in body


def test_confirmation_shows_full_prompt_not_truncated(client, fake_clients):  # type: ignore[no-untyped-def]
    sig = _seed_session_and_subscription(client, fake_clients)
    resp = client.get(f"/confirmation/SUB-007?session={sig.session_id}")
    assert "Full prompt text: create customer Ada on PLAN_M with MSISDN 90000042" in resp.text
