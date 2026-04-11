"""Tests for AuthProvider protocol and NoAuthProvider."""

import pytest
import respx
from httpx import Response

from bss_clients import AuthProvider, BSSClient, NoAuthProvider


BASE_URL = "http://test-service:8000"


class TestNoAuthProvider:
    @pytest.mark.asyncio
    async def test_returns_empty_headers(self):
        provider = NoAuthProvider()
        headers = await provider.get_headers()
        assert headers == {}

    def test_implements_protocol(self):
        assert isinstance(NoAuthProvider(), AuthProvider)


class TestCustomAuthProvider:
    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_auth_headers_injected(self):
        """Custom AuthProvider headers appear on outgoing requests."""

        class BearerAuth:
            async def get_headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer tok_test_123"}

        client = BSSClient(base_url=BASE_URL, auth_provider=BearerAuth())
        route = respx.get(f"{BASE_URL}/protected").mock(
            return_value=Response(200, json={"ok": True})
        )

        await client._request("GET", "/protected")

        assert route.called
        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer tok_test_123"

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_called_on_every_request(self):
        """AuthProvider.get_headers() is called per-request, not cached."""
        call_count = 0

        class CountingAuth:
            async def get_headers(self) -> dict[str, str]:
                nonlocal call_count
                call_count += 1
                return {"Authorization": f"Bearer tok_{call_count}"}

        client = BSSClient(base_url=BASE_URL, auth_provider=CountingAuth())
        respx.get(f"{BASE_URL}/thing").mock(
            return_value=Response(200, json={})
        )

        await client._request("GET", "/thing")
        await client._request("GET", "/thing")

        assert call_count == 2
