"""Unit tests for BSSApiTokenMiddleware against a throwaway FastAPI app.

Per V0_3_0.md test strategy: prove middleware behavior in isolation
before wiring into real services. Cases:

- /health passes through without a token (exemption)
- Missing X-BSS-API-Token header → 401 AUTH_MISSING_TOKEN
- Wrong token → 401 AUTH_INVALID_TOKEN
- Right token → 200 (handler ran)

Bonus: exemption boundary checks — /healthz must NOT be exempt
(only the literal three paths in EXEMPT_PATHS).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bss_middleware import (
    AUTH_INVALID_TOKEN,
    AUTH_MISSING_TOKEN,
    BSSApiTokenMiddleware,
    TEST_TOKEN,
)


def _make_app(token: str = TEST_TOKEN) -> FastAPI:
    app = FastAPI()
    app.add_middleware(BSSApiTokenMiddleware, token=token)

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        return {"ready": True}

    @app.get("/healthz")
    async def healthz():
        # Note: NOT in EXEMPT_PATHS — must require token.
        return {"ok": True}

    return app


@pytest.fixture
async def client():
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_exempt_no_token(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200


async def test_health_ready_exempt_no_token(client: AsyncClient) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200


async def test_root_without_token_returns_401_missing(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == AUTH_MISSING_TOKEN
    assert "X-BSS-API-Token" in body["message"]


async def test_root_with_wrong_token_returns_401_invalid(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-BSS-API-Token": "wrong-token-value"})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == AUTH_INVALID_TOKEN
    # The error message must NOT echo the provided wrong token back.
    assert "wrong-token-value" not in json.dumps(body)


async def test_root_with_correct_token_returns_200(client: AsyncClient) -> None:
    r = await client.get("/", headers={"X-BSS-API-Token": TEST_TOKEN})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_healthz_not_exempt(client: AsyncClient) -> None:
    """Only the literal three paths in EXEMPT_PATHS bypass auth."""
    r = await client.get("/healthz")
    assert r.status_code == 401


async def test_header_name_is_case_insensitive(client: AsyncClient) -> None:
    """ASGI headers are bytes; check case-insensitive lookup."""
    r = await client.get("/", headers={"x-bss-api-token": TEST_TOKEN})
    assert r.status_code == 200


async def test_token_comparison_uses_constant_time() -> None:
    """Inspect the source — the middleware MUST use hmac.compare_digest.

    A regression that swapped to ``==`` would silently work in tests
    (functionally equivalent for byte strings) but would re-introduce
    a timing oracle. Asserting on the source is the simplest way to
    keep that property tied to the test suite.
    """
    import inspect

    from bss_middleware import token_auth

    src = inspect.getsource(token_auth)
    assert "hmac.compare_digest" in src
    # Negative: no naive comparison of `provided` vs the stored token.
    assert "provided == self._token" not in src
    assert "provided.encode() == self._token" not in src
