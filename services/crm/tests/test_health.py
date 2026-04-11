"""Health and readiness endpoint tests."""

from httpx import AsyncClient


class TestHealth:
    async def test_health(self, client: AsyncClient):
        r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "crm"
        assert body["version"] == "0.1.0"

    async def test_ready(self, client: AsyncClient):
        r = await client.get("/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    async def test_request_id_header(self, client: AsyncClient):
        r = await client.get("/health")
        assert "x-request-id" in r.headers
