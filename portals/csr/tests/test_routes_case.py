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
    the canned case payload that test setup mutates.

    v0.12 extends the fixture: tests can mutate
    ``fake_clients.crm.transcripts`` to plant chat-transcript bodies
    keyed by hash. ``fake_clients.crm.transcript_get_error`` (Exception
    or None) lets a test simulate an upstream fetch failure so the
    "transcript no longer retrievable" empty state can be exercised.
    """

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
            self.transcripts: dict[str, dict] = {}
            self.transcript_get_error: Exception | None = None

        async def get_case(self, case_id: str):
            from bss_clients.errors import ClientError
            if case_id != "CASE-042":
                raise ClientError(404, "no such case")
            return dict(self.case_raw)

        async def get_chat_transcript(self, hash_: str):
            if self.transcript_get_error is not None:
                err = self.transcript_get_error
                self.transcript_get_error = None
                raise err
            from bss_clients.errors import ClientError
            if hash_ not in self.transcripts:
                raise ClientError(404, f"transcript {hash_} not found")
            return dict(self.transcripts[hash_])

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


# ── v0.12 PR8: chat transcript panel ─────────────────────────────────


def test_case_thread_renders_transcript_panel_when_hash_present(
    authed_client_with_case,
):  # type: ignore[no-untyped-def]
    crm = authed_client_with_case.app.state  # placeholder for clarity
    # Reach into the override class to plant the transcript body and
    # link the case to the hash.
    from unittest.mock import patch as _p

    with _p.dict(
        authed_client_with_case.app.state.__dict__,
        {},
    ):
        pass  # no-op; we mutate via the route's get_clients patch instead.

    # Walk the patched CRM through the route's get_clients import.
    import bss_csr.routes.case as case_route

    fake_crm = case_route.get_clients().crm
    fake_crm.case_raw["chatTranscriptHash"] = "deadbeef" * 8
    fake_crm.transcripts["deadbeef" * 8] = {
        "hash": "deadbeef" * 8,
        "customer_id": "CUST-test01",
        "body": (
            "User: I think someone took over my account\n"
            "Assistant: That sounds like fraud — escalating.\n"
        ),
        "recorded_at": "2026-04-27T14:00:00+00:00",
    }

    resp = authed_client_with_case.get("/case/CASE-042")
    assert resp.status_code == 200
    body = resp.text
    assert "Chat transcript" in body
    assert "deadbeefdeadbeef" in body  # truncated hash header
    assert "took over my account" in body
    assert "That sounds like fraud" in body


def test_case_thread_no_transcript_section_when_hash_absent(
    authed_client_with_case,
):  # type: ignore[no-untyped-def]
    # Default fixture has no chatTranscriptHash on case_raw.
    resp = authed_client_with_case.get("/case/CASE-042")
    assert resp.status_code == 200
    assert "Chat transcript" not in resp.text


def test_case_thread_transcript_fetch_error_renders_empty_state(
    authed_client_with_case,
):  # type: ignore[no-untyped-def]
    """When the case carries a hash but the transcript fetch fails
    (archived, service down), the panel renders the friendly empty
    state rather than the case page erroring out."""
    import bss_csr.routes.case as case_route
    from bss_clients.errors import ClientError

    fake_crm = case_route.get_clients().crm
    fake_crm.case_raw["chatTranscriptHash"] = "feedfeed" * 8
    fake_crm.transcript_get_error = ClientError(503, "transcripts unavailable")

    resp = authed_client_with_case.get("/case/CASE-042")
    assert resp.status_code == 200
    body = resp.text
    assert "Chat transcript" in body
    assert "no longer retrievable" in body
