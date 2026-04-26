"""Account-first signup funnel tests (PR 4).

Covers the v0.8 doctrine pieces specifically:

* /signup/{plan}, /signup/{plan}/msisdn, POST /signup all redirect to
  /auth/login when no session is present (the gating bites).
* /welcome and /plans are public — render without a session.
* The agent_events stream calls link_to_customer the moment a CUST-*
  id is harvested, atomically binding the verified identity to the
  customer record. Verified by inspecting the identity row after the
  stream finishes.
* If the visitor abandons mid-flow (no final agent message), the
  identity is still linked to the customer that was created — so a
  returning visitor gets the same customer record under the same email.
* link_to_customer is idempotent on retry — a second stream with the
  same (identity, customer) pair doesn't raise.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from bss_orchestrator.session import (
    AgentEventFinalMessage,
    AgentEventPromptReceived,
    AgentEventToolCallCompleted,
    AgentEventToolCallStarted,
)
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault(
    "BSS_PORTAL_TOKEN_PEPPER",
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
)
os.environ.setdefault("BSS_PORTAL_EMAIL_ADAPTER", "noop")
os.environ.setdefault("BSS_PORTAL_DEV_INSECURE_COOKIE", "1")

from bss_clock.clock import reset_for_tests as _reset_clock  # noqa: E402
from bss_models import Identity  # noqa: E402
from bss_portal_auth.test_helpers import create_test_session  # noqa: E402

from bss_self_serve.config import Settings  # noqa: E402
from bss_self_serve.main import create_app  # noqa: E402
from bss_self_serve.middleware import PORTAL_SESSION_COOKIE  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[3]


class _DbSettings(BaseSettings):
    BSS_DB_URL: str = ""
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@pytest.fixture(autouse=True)
def _clock():
    _reset_clock()
    yield
    _reset_clock()


@pytest.fixture
def db_url() -> str:
    url = _DbSettings().BSS_DB_URL or os.environ.get("BSS_DB_URL", "")
    if not url:
        pytest.fail("BSS_DB_URL is not set. Export it or add to .env.")
    os.environ["BSS_DB_URL"] = url
    return url


@pytest_asyncio.fixture
async def seed_db(db_url: str):
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE portal_auth.login_attempt, portal_auth.session, "
            "portal_auth.login_token, portal_auth.identity RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    yield factory
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE portal_auth.login_attempt, portal_auth.session, "
            "portal_auth.login_token, portal_auth.identity RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()


# ── Public allowlist (no session required) ───────────────────────────────


def test_welcome_is_public(seed_db, fake_clients):
    with patch(
        "bss_self_serve.routes.welcome.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            resp = c.get("/welcome")
            assert resp.status_code == 200
            assert "bss-cli self-serve" in resp.text
            # Anonymous visitor sees the Sign-in CTA, not "My account".
            assert "Sign in" in resp.text
            assert "/auth/login" in resp.text


def test_plans_is_public(seed_db, fake_clients):
    with patch(
        "bss_self_serve.routes.welcome.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            resp = c.get("/plans")
            assert resp.status_code == 200
            assert "PLAN_M" in resp.text
            # Anonymous CTA bounces through /auth/login with next= preserved.
            assert "/auth/login?next=/signup/PLAN_M/msisdn" in resp.text


# ── Gated entry points redirect when no session ──────────────────────────


def test_signup_form_without_session_redirects_to_login(seed_db, fake_clients):
    with patch(
        "bss_self_serve.routes.signup.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            resp = c.get("/signup/PLAN_M?msisdn=90000042", follow_redirects=False)
            assert resp.status_code == 303
            loc = resp.headers["location"]
            assert loc.startswith("/auth/login")
            # next= preserves the originating path so post-login lands here again
            assert "next=" in loc
            assert "PLAN_M" in loc


def test_msisdn_picker_without_session_redirects_to_login(seed_db, fake_clients):
    with patch(
        "bss_self_serve.routes.msisdn_picker.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            resp = c.get("/signup/PLAN_M/msisdn", follow_redirects=False)
            assert resp.status_code == 303
            assert resp.headers["location"].startswith("/auth/login")


def test_signup_post_without_session_redirects_to_login(seed_db, fake_clients):
    with patch(
        "bss_self_serve.routes.signup.get_clients", return_value=fake_clients
    ):
        app = create_app(Settings())
        with TestClient(app) as c:
            resp = c.post(
                "/signup",
                data={
                    "plan": "PLAN_M",
                    "name": "Ada",
                    "email": "ada@x.sg",
                    "phone": "+6590001234",
                    "msisdn": "90000042",
                    "card_pan": "4242424242424242",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303
            assert resp.headers["location"].startswith("/auth/login")


# ── link_to_customer atomicity ───────────────────────────────────────────


def _canned_signup_stream():
    """Mocked agent stream that emits a CUST-* id from customer.create."""
    return [
        AgentEventPromptReceived(prompt="Create customer Ada on PLAN_M…"),
        AgentEventToolCallStarted(
            name="customer.create", args={"name": "Ada"}, call_id="c1"
        ),
        AgentEventToolCallCompleted(
            name="customer.create",
            call_id="c1",
            result='{"id": "CUST-042"}',
        ),
        AgentEventToolCallStarted(
            name="order.create", args={"offering_id": "PLAN_M"}, call_id="c2"
        ),
        AgentEventToolCallCompleted(
            name="order.create",
            call_id="c2",
            result='{"id": "ORD-014", "state": "acknowledged"}',
        ),
        AgentEventFinalMessage(
            text="Signup complete. Subscription SUB-007 is active on PLAN_M."
        ),
    ]


@pytest.mark.asyncio
async def test_link_to_customer_runs_when_customer_create_returns_id(
    seed_db, fake_clients
):
    """The full happy path: identity exists, signup runs, identity is linked."""
    async with seed_db() as db:
        sess, identity = await create_test_session(db, email="ada@x.sg")
        await db.commit()
        sid = sess.id
        identity_id = identity.id

    canned = _canned_signup_stream()

    async def fake_drive_signup(**_kwargs) -> AsyncIterator:  # type: ignore[no-untyped-def]
        for e in canned:
            yield e

    with patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.agent_events.drive_signup", new=fake_drive_signup):
        app = create_app(Settings())
        with TestClient(app) as c:
            c.cookies.set(PORTAL_SESSION_COOKIE, sid)
            sub = c.post(
                "/signup",
                data={
                    "plan": "PLAN_M",
                    "name": "Ada",
                    "email": "ada@x.sg",
                    "phone": "+6590001234",
                    "msisdn": "90000042",
                    "card_pan": "4242424242424242",
                },
                follow_redirects=False,
            )
            assert sub.status_code == 303
            session_id = sub.headers["location"].split("session=")[-1]
            # Drain the SSE stream — drive_signup runs to completion.
            _ = c.get(f"/agent/events/{session_id}").text

    # Identity is now linked to CUST-042.
    async with seed_db() as db:
        row = (
            await db.execute(select(Identity).where(Identity.id == identity_id))
        ).scalar_one()
        assert row.customer_id == "CUST-042"
        assert row.status == "registered"


@pytest.mark.asyncio
async def test_link_to_customer_persists_when_visitor_abandons_after_customer_create(
    seed_db, fake_clients
):
    """Mid-flow bail: customer.create succeeded, agent crashed before final.

    The identity should STILL be linked to the customer — that's the
    "abandoned-cart hygiene" doctrine in V0_8_0.md §3.5. Returning
    visitor under the same email gets their existing customer record.
    """
    async with seed_db() as db:
        sess, identity = await create_test_session(db, email="ada@x.sg")
        await db.commit()
        sid = sess.id
        identity_id = identity.id

    # Truncated stream — emits the customer.create result, then quits.
    truncated = [
        AgentEventPromptReceived(prompt="Create customer Ada…"),
        AgentEventToolCallStarted(
            name="customer.create", args={"name": "Ada"}, call_id="c1"
        ),
        AgentEventToolCallCompleted(
            name="customer.create",
            call_id="c1",
            result='{"id": "CUST-042"}',
        ),
        # No final message — simulates the agent bailing here.
    ]

    async def fake_drive_signup(**_kwargs) -> AsyncIterator:  # type: ignore[no-untyped-def]
        for e in truncated:
            yield e

    with patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.agent_events.drive_signup", new=fake_drive_signup):
        app = create_app(Settings())
        with TestClient(app) as c:
            c.cookies.set(PORTAL_SESSION_COOKIE, sid)
            sub = c.post(
                "/signup",
                data={
                    "plan": "PLAN_M",
                    "name": "Ada",
                    "email": "ada@x.sg",
                    "phone": "+6590001234",
                    "msisdn": "90000042",
                    "card_pan": "4242424242424242",
                },
                follow_redirects=False,
            )
            session_id = sub.headers["location"].split("session=")[-1]
            _ = c.get(f"/agent/events/{session_id}").text

    async with seed_db() as db:
        row = (
            await db.execute(select(Identity).where(Identity.id == identity_id))
        ).scalar_one()
        # Linked even though the agent never said "complete".
        assert row.customer_id == "CUST-042"


@pytest.mark.asyncio
async def test_link_to_customer_idempotent_on_retry(seed_db, fake_clients):
    """Re-running a signup stream that re-asserts the same customer is OK."""
    async with seed_db() as db:
        sess, identity = await create_test_session(db, email="ada@x.sg")
        await db.commit()
        sid = sess.id
        identity_id = identity.id

    canned = _canned_signup_stream()

    async def fake_drive_signup(**_kwargs) -> AsyncIterator:  # type: ignore[no-untyped-def]
        for e in canned:
            yield e

    with patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.agent_events.drive_signup", new=fake_drive_signup):
        app = create_app(Settings())
        with TestClient(app) as c:
            c.cookies.set(PORTAL_SESSION_COOKIE, sid)
            # Two parallel signup attempts re-using the same identity.
            for _ in range(2):
                sub = c.post(
                    "/signup",
                    data={
                        "plan": "PLAN_M",
                        "name": "Ada",
                        "email": "ada@x.sg",
                        "phone": "+6590001234",
                        "msisdn": "90000042",
                        "card_pan": "4242424242424242",
                    },
                    follow_redirects=False,
                )
                session_id = sub.headers["location"].split("session=")[-1]
                _ = c.get(f"/agent/events/{session_id}").text

    # Still linked to CUST-042; no exception, no double-linking.
    async with seed_db() as db:
        row = (
            await db.execute(select(Identity).where(Identity.id == identity_id))
        ).scalar_one()
        assert row.customer_id == "CUST-042"
