"""Customer 360 view — read-only assembly of 6 sections."""

from __future__ import annotations

from conftest import sample_customer, sample_subscription  # type: ignore[import-not-found]


def test_customer_360_requires_login(client):  # type: ignore[no-untyped-def]
    resp = client.get("/customer/CUST-test01", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_customer_360_renders_summary_subscriptions_cases_payments(
    authed_client, fake_clients
):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_id["CUST-test01"] = sample_customer()
    fake_clients.subscription.by_customer["CUST-test01"] = [
        {"id": "SUB-007"},
    ]
    fake_clients.subscription.by_id["SUB-007"] = sample_subscription()
    fake_clients.crm.cases["CUST-test01"] = [
        {
            "id": "CASE-042",
            "subject": "Data not working",
            "state": "open",
            "priority": "high",
            "tickets": [{"state": "open"}],
        },
    ]
    fake_clients.payment.by_customer["CUST-test01"] = [
        {
            "id": "PM-1085",
            "cardSummary": {"brand": "visa", "last4": "4242", "expMonth": 12, "expYear": 2030},
            "isDefault": True,
            "status": "active",
        },
    ]
    fake_clients.crm.interactions["CUST-test01"] = [
        {
            "id": "INT-001",
            "channel": "portal-csr",
            "direction": "inbound",
            "summary": "Operator opened the customer view",
            "occurredAt": "2026-04-23T01:00:00Z",
        },
    ]

    resp = authed_client.get("/customer/CUST-test01")
    assert resp.status_code == 200
    body = resp.text
    # Customer summary
    assert "Ada Lovelace" in body
    assert "CUST-test01" in body
    # Subscription card with state + plan + balance
    assert "SUB-007" in body
    assert "PLAN_M" in body
    assert "5120" in body  # remaining data
    # Cases
    assert "CASE-042" in body
    assert "Data not working" in body
    # Payment
    assert "VISA" in body
    assert "4242" in body
    # Interactions
    assert "Operator opened the customer view" in body
    assert "portal-csr" in body
    # Ask form is on the page
    assert "Ask about this customer" in body


def test_customer_360_unknown_id_404s(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/customer/CUST-NOPE")
    assert resp.status_code == 404


def test_customer_360_with_session_query_attaches_sse(
    authed_client, fake_clients
):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_id["CUST-test01"] = sample_customer()
    resp = authed_client.get("/customer/CUST-test01?session=abc123")
    assert resp.status_code == 200
    # base.html opens the SSE connection because session_id is set + stream_live
    assert 'sse-connect="/agent/events/abc123"' in resp.text


def test_customer_360_without_session_does_not_attach_sse(
    authed_client, fake_clients
):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_id["CUST-test01"] = sample_customer()
    resp = authed_client.get("/customer/CUST-test01")
    assert "sse-connect" not in resp.text


def test_summary_partial_renders_just_the_card(authed_client, fake_clients):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_id["CUST-test01"] = sample_customer()
    resp = authed_client.get("/customer/CUST-test01/summary")
    assert resp.status_code == 200
    # No <html> or <body> — partial only.
    assert "Ada Lovelace" in resp.text
    assert "<html" not in resp.text
