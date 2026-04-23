"""Case thread drill-in — read-only view."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bss_csr.config import Settings
from bss_csr.main import create_app
from conftest import FakeBundle  # type: ignore[import-not-found]


@pytest.fixture
def authed_client_with_case(fake_clients: FakeBundle):
    """TestClient with a logged-in operator; ``client.case_raw`` exposes
    the canned case payload that test setup mutates."""

    case_raw = {
        "id": "CASE-042",
        "subject": "Data not working",
        "state": "open",
        "priority": "high",
        "category": "technical",
        "agentId": "csr-demo-001",
        "customerId": "CUST-test01",
        "createdAt": "2026-04-23T01:00:00Z",
        "tickets": [
            {
                "id": "TKT-101",
                "ticketType": "subscription",
                "subject": "Bundle exhausted",
                "state": "open",
                "agentId": "csr-demo-001",
            },
        ],
        "notes": [
            {
                "id": "NOTE-1",
                "body": "Customer called; investigating.",
                "createdBy": "csr-demo-001",
                "createdAt": "2026-04-23T01:05:00Z",
            },
        ],
    }

    class _FakeCRMOverride:
        def __init__(self, base):
            self._base = base
            self.case_raw = case_raw

        async def get_case(self, case_id: str):
            from bss_clients.errors import ClientError
            if case_id != "CASE-042":
                raise ClientError(404, "no such case")
            return dict(self.case_raw)

        def __getattr__(self, item):
            return getattr(self._base, item)

    fake_clients.crm = _FakeCRMOverride(fake_clients.crm)  # type: ignore[assignment]

    with patch("bss_csr.routes.search.get_clients", return_value=fake_clients), \
         patch("bss_csr.routes.customer.get_clients", return_value=fake_clients), \
         patch("bss_csr.routes.case.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            login = c.post(
                "/login", data={"username": "csr-demo-001"}, follow_redirects=False
            )
            assert login.status_code == 303
            yield c


def test_case_thread_renders_header_tickets_and_notes(authed_client_with_case):  # type: ignore[no-untyped-def]
    resp = authed_client_with_case.get("/case/CASE-042")
    assert resp.status_code == 200
    body = resp.text
    assert "CASE-042" in body
    assert "Data not working" in body
    assert "TKT-101" in body
    assert "Bundle exhausted" in body
    assert "Customer called; investigating." in body
    # Back-link to customer
    assert 'href="/customer/CUST-test01"' in body


def test_case_thread_unknown_case_404s(authed_client_with_case):  # type: ignore[no-untyped-def]
    resp = authed_client_with_case.get("/case/CASE-NOPE")
    assert resp.status_code == 404


def test_case_thread_requires_login(client):  # type: ignore[no-untyped-def]
    resp = client.get("/case/CASE-042", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
