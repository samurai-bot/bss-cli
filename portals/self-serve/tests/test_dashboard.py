"""Login-gated `/` + empty-dashboard placeholder (PR 5).

V0_8_0.md §3.4, §3.5:

* No session            -> 303 to /auth/login.
* Session, identity unlinked (verified email but no customer) ->
  empty dashboard with a "Browse plans" CTA.
* Session, identity linked  -> placeholder dashboard naming the
  customer; v0.10 will fill in the actual lines/balances UI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault(
    "BSS_PORTAL_TOKEN_PEPPER",
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
)
os.environ.setdefault("BSS_PORTAL_EMAIL_ADAPTER", "noop")
os.environ.setdefault("BSS_PORTAL_DEV_INSECURE_COOKIE", "1")

from bss_clock.clock import reset_for_tests as _reset_clock  # noqa: E402
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


# ── No session ──────────────────────────────────────────────────────────


def test_root_redirects_to_login_when_no_session(seed_db):
    # routes/landing.py is the dashboard now — no catalog reads, so no
    # get_clients to patch. Just stand the app up and hit `/`.
    app = create_app(Settings())
    with TestClient(app) as c:
        resp = c.get("/", follow_redirects=False)
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert loc.startswith("/auth/login")
        assert "next=" in loc


# ── Verified-but-unlinked identity ──────────────────────────────────────


@pytest.mark.asyncio
async def test_root_renders_empty_dashboard_for_unlinked_identity(seed_db):
    async with seed_db() as db:
        sess, identity = await create_test_session(
            db, email="ada@example.sg", customer_id=None, verified=True
        )
        await db.commit()
        sid = sess.id
        assert identity.customer_id is None

    app = create_app(Settings())
    with TestClient(app) as c:
        c.cookies.set(PORTAL_SESSION_COOKIE, sid)
        resp = c.get("/")
        assert resp.status_code == 200
        body = resp.text
        # Email greeting + empty-state copy + CTA into /plans
        assert "ada@example.sg" in body
        # Apostrophe pass-through varies between FastAPI/Jinja versions;
        # match a substring that doesn't include it.
        assert "any lines yet" in body
        assert "/plans" in body
        # Logout form is on the empty dashboard so a stuck visitor can sign out.
        assert 'action="/auth/logout"' in body


# ── Verified + linked identity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_root_renders_placeholder_dashboard_for_linked_identity(seed_db):
    async with seed_db() as db:
        sess, identity = await create_test_session(
            db, email="ada@example.sg", customer_id="CUST-042", verified=True
        )
        await db.commit()
        sid = sess.id

    app = create_app(Settings())
    with TestClient(app) as c:
        c.cookies.set(PORTAL_SESSION_COOKIE, sid)
        resp = c.get("/")
        assert resp.status_code == 200
        body = resp.text
        assert "My account" in body
        assert "ada@example.sg" in body
        assert "CUST-042" in body
        # Placeholder copy points at v0.10 — confirms we're on the
        # linked-dashboard template, not the empty-dashboard fallback.
        assert "v0.10" in body


# ── Public surfaces still untouched ─────────────────────────────────────


def test_welcome_still_public_after_dashboard_lands(seed_db, fake_clients):
    """Sanity: PR 5's `/` change doesn't accidentally gate /welcome."""
    from unittest.mock import patch

    with patch("bss_self_serve.routes.welcome.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            assert c.get("/welcome").status_code == 200
            assert c.get("/plans").status_code == 200
