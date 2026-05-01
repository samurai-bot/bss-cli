"""Tests for the v0.13 operator cockpit browser routes.

Replaces the v0.5 test surface (test_health.py login + search +
test_routes_ask_and_sse + test_routes_search + test_routes_customer)
which all exercised the retired stub-login + customer-360 + ask-form
plumbing.

Each test boots ``create_app`` against the dev DB (via the shared
ConversationStore), truncates ``cockpit.*`` before+after, and makes
HTTP requests via FastAPI's ``TestClient``.

Doctrine guards live in test_no_staff_auth.py; this file covers the
positive routes:
- GET /                   → sessions index renders for the operator
- POST /cockpit/new       → opens a session, 303s to the thread
- GET /cockpit/{id}       → renders the thread page; 404 on unknown id
- POST /cockpit/{id}/turn → appends a user turn, 303s back
- POST /cockpit/{id}/reset → clears messages
- POST /cockpit/{id}/focus → set + clear customer focus
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bss_csr.config import Settings
from bss_csr.main import create_app


_REPO_ROOT = Path(__file__).resolve().parents[3]


class _DbSettings(BaseSettings):
    BSS_DB_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@pytest.fixture
def db_url() -> str:
    url = _DbSettings().BSS_DB_URL or os.environ.get("BSS_DB_URL", "")
    if not url:
        pytest.skip("BSS_DB_URL not set; skipping cockpit DB tests.")
    return url


@pytest.fixture
def cockpit_client(db_url: str, monkeypatch):
    """Boot a fresh cockpit app and TestClient, with cockpit.* truncated."""
    monkeypatch.setenv("BSS_DB_URL", db_url)
    # Ensure the test sees a clean cockpit schema.
    import asyncio

    async def _truncate():
        engine = create_async_engine(db_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            await s.execute(text(
                "TRUNCATE cockpit.pending_destructive, cockpit.message, "
                "cockpit.session RESTART IDENTITY CASCADE"
            ))
            await s.commit()
        await engine.dispose()

    asyncio.run(_truncate())

    app = create_app(Settings())
    with TestClient(app) as c:
        yield c

    # Truncate after each test too so independent runs don't pile up.
    asyncio.run(_truncate())


# ── Sessions index ────────────────────────────────────────────────────


def test_index_renders_empty_state_when_no_sessions(cockpit_client) -> None:
    r = cockpit_client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "Cockpit sessions" in body
    assert "No active cockpit sessions" in body or "New session" in body


# ── New / open / resume ───────────────────────────────────────────────


def test_post_new_opens_session_and_303s_to_thread(cockpit_client) -> None:
    r = cockpit_client.post(
        "/cockpit/new", data={"label": "diagnose-test"}, follow_redirects=False
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/cockpit/SES-")
    # Follow to the thread page.
    r2 = cockpit_client.get(location)
    assert r2.status_code == 200
    assert "diagnose-test" in r2.text or "operator cockpit" in r2.text.lower()


def test_get_thread_unknown_id_404s(cockpit_client) -> None:
    r = cockpit_client.get("/cockpit/SES-19000101-deadbeef")
    assert r.status_code == 404


# ── Turn append + 303 ─────────────────────────────────────────────────


def test_post_turn_appends_user_message_and_redirects(cockpit_client) -> None:
    new = cockpit_client.post(
        "/cockpit/new", data={"label": ""}, follow_redirects=False
    )
    location = new.headers["location"]
    sid = location.split("/")[-1]
    r = cockpit_client.post(
        f"/cockpit/{sid}/turn",
        data={"message": "show me CUST-001"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Page reload should now show the user message in the thread.
    page = cockpit_client.get(f"/cockpit/{sid}").text
    assert "show me CUST-001" in page


def test_post_turn_empty_message_redirects_without_appending(cockpit_client) -> None:
    new = cockpit_client.post(
        "/cockpit/new", follow_redirects=False
    )
    sid = new.headers["location"].split("/")[-1]
    r = cockpit_client.post(
        f"/cockpit/{sid}/turn", data={"message": "  "}, follow_redirects=False
    )
    assert r.status_code == 303
    # Thread is still empty.
    page = cockpit_client.get(f"/cockpit/{sid}").text
    # No bubble class for a user turn should be present.
    assert "chat-bubble-user" not in page


# ── Reset / focus / confirm ───────────────────────────────────────────


def test_post_reset_clears_messages(cockpit_client) -> None:
    new = cockpit_client.post("/cockpit/new", follow_redirects=False)
    sid = new.headers["location"].split("/")[-1]
    cockpit_client.post(
        f"/cockpit/{sid}/turn", data={"message": "hello"}, follow_redirects=False
    )
    assert "hello" in cockpit_client.get(f"/cockpit/{sid}").text

    r = cockpit_client.post(f"/cockpit/{sid}/reset", follow_redirects=False)
    assert r.status_code == 303
    page = cockpit_client.get(f"/cockpit/{sid}").text
    assert "hello" not in page


def test_post_focus_set_and_clear(cockpit_client) -> None:
    new = cockpit_client.post("/cockpit/new", follow_redirects=False)
    sid = new.headers["location"].split("/")[-1]
    r = cockpit_client.post(
        f"/cockpit/{sid}/focus",
        data={"customer_id": "CUST-007"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = cockpit_client.get(f"/cockpit/{sid}").text
    # The focus form's input value should reflect the pinned id.
    assert "CUST-007" in page

    cockpit_client.post(
        f"/cockpit/{sid}/focus",
        data={"customer_id": ""},
        follow_redirects=False,
    )
    page2 = cockpit_client.get(f"/cockpit/{sid}").text
    # Cleared focus — no CUST-007 in the focus input value attr.
    assert 'value="CUST-007"' not in page2


def test_post_confirm_is_a_no_op_marker(cockpit_client) -> None:
    new = cockpit_client.post("/cockpit/new", follow_redirects=False)
    sid = new.headers["location"].split("/")[-1]
    r = cockpit_client.post(f"/cockpit/{sid}/confirm", follow_redirects=False)
    assert r.status_code == 303


# ── Health ────────────────────────────────────────────────────────────


def test_health_endpoint(cockpit_client) -> None:
    r = cockpit_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "portal-csr"
    assert body["version"].startswith("0.13")
