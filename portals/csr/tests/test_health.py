"""CSR portal scaffold smoke test."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bss_csr.config import Settings
from bss_csr.main import create_app


def test_health_endpoint_returns_ok() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "portal-csr"
    assert body["version"].startswith("0.5")


def test_login_form_renders() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        resp = client.get("/login")
    assert resp.status_code == 200
    assert "CSR Console" in resp.text
    assert "Accepts any credentials" in resp.text


def test_login_post_creates_session_and_redirects_to_search() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        resp = client.post(
            "/login",
            data={"username": "csr-demo-001", "password": "ignored"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/search"
    assert "bss_csr_session" in resp.cookies


def test_search_redirects_to_login_without_cookie() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        resp = client.get("/search", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_logout_clears_cookie_and_redirects() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "csr-demo-001"},
            follow_redirects=False,
        )
        token = login.cookies["bss_csr_session"]
        resp = client.post(
            "/logout",
            cookies={"bss_csr_session": token},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
