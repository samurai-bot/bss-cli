"""CatalogClient — service-to-service client for Catalog.

Scaffold for Phase 6 (COM needs get_offering for price lookup).
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class CatalogClient(BSSClient):
    """Client for the Catalog service (port 8001)."""

    def __init__(
        self,
        base_url: str = "http://catalog:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    async def get_offering(self, offering_id: str) -> dict[str, Any]:
        """GET /tmf-api/productCatalogManagement/v4/productOffering/{id}."""
        resp = await self._request(
            "GET",
            f"/tmf-api/productCatalogManagement/v4/productOffering/{offering_id}",
        )
        return resp.json()

    async def list_offerings(self) -> list[dict[str, Any]]:
        """GET /tmf-api/productCatalogManagement/v4/productOffering."""
        resp = await self._request(
            "GET",
            "/tmf-api/productCatalogManagement/v4/productOffering",
        )
        return resp.json()

    async def get_vas(self, vas_id: str) -> dict[str, Any]:
        """GET /vas/offering/{vas_id}."""
        resp = await self._request("GET", f"/vas/offering/{vas_id}")
        return resp.json()

    async def list_vas(self) -> list[dict[str, Any]]:
        """GET /vas/offering."""
        resp = await self._request("GET", "/vas/offering")
        return resp.json()
