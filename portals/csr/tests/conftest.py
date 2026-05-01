"""Shared fixtures for CSR portal (v0.13 cockpit) tests.

The v0.13 cockpit collapses the v0.5 portal pattern; the test surface
here covers the two remaining route files:

* ``routes/cockpit.py`` — driven by tests in ``test_cockpit_routes.py``
  against the dev DB (no mocked clients; the cockpit's read paths are
  exercised at the route layer with real Postgres).
* ``routes/case.py`` — read-only deep link, exercised in
  ``test_routes_case.py`` against a mocked CRM client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bss_csr.config import Settings
from bss_csr.main import create_app


# ─── Fake CRM client (used only by test_routes_case.py) ──────────────


@dataclass
class FakeCRM:
    case_raw: dict[str, Any] | None = None
    case_404: bool = False
    tickets_by_case: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    transcripts: dict[str, dict[str, Any]] = field(default_factory=dict)
    transcript_get_error: Exception | None = None

    async def get_case(self, case_id: str) -> dict[str, Any]:
        if self.case_404:
            from bss_clients.errors import ClientError
            raise ClientError(404, f"Case {case_id} not found")
        if self.case_raw is None:
            from bss_clients.errors import ClientError
            raise ClientError(404, f"Case {case_id} not found")
        return dict(self.case_raw)

    async def list_tickets(self, *, case_id: str) -> list[dict[str, Any]]:
        return list(self.tickets_by_case.get(case_id, []))

    async def get_chat_transcript(self, transcript_hash: str) -> dict[str, Any]:
        if self.transcript_get_error is not None:
            raise self.transcript_get_error
        return dict(self.transcripts[transcript_hash])


@dataclass
class FakeBundle:
    crm: FakeCRM = field(default_factory=FakeCRM)


@pytest.fixture
def fake_clients() -> FakeBundle:
    return FakeBundle()


@pytest.fixture
def case_client(fake_clients: FakeBundle, monkeypatch):
    """TestClient with the case route's get_clients() patched.

    Only used by test_routes_case.py — the cockpit-routes tests
    exercise the real DB-backed flow and use their own fixture.
    """
    # Provide a no-op DB URL so lifespan can construct the store; the
    # case route doesn't touch it.
    monkeypatch.setenv(
        "BSS_DB_URL",
        monkeypatch.delenv("BSS_DB_URL", raising=False) or "postgresql+asyncpg://bss:bss_password@localhost:5432/bss",
    )
    with patch(
        "bss_csr.routes.case.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            yield c
