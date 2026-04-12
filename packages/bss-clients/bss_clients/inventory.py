"""InventoryClient — service-to-service client for CRM's Inventory sub-domain.

Inventory lives inside CRM (port 8002) under /inventory-api/v1/.
This client isolates callers from that hosting detail.
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class InventoryClient(BSSClient):
    """Client for the Inventory sub-domain (hosted on CRM, port 8002)."""

    def __init__(
        self,
        base_url: str = "http://crm:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    # ── MSISDN ──────────────────────────────────────────────────────

    async def get_msisdn(self, msisdn: str) -> dict[str, Any]:
        """GET /inventory-api/v1/msisdn/{msisdn}."""
        resp = await self._request(
            "GET", f"/inventory-api/v1/msisdn/{msisdn}"
        )
        return resp.json()

    async def reserve_msisdn(self, msisdn: str) -> dict[str, Any]:
        """POST /inventory-api/v1/msisdn/{msisdn}/reserve."""
        resp = await self._request(
            "POST", f"/inventory-api/v1/msisdn/{msisdn}/reserve"
        )
        return resp.json()

    async def assign_msisdn(self, msisdn: str) -> dict[str, Any]:
        """POST /inventory-api/v1/msisdn/{msisdn}/assign."""
        resp = await self._request(
            "POST", f"/inventory-api/v1/msisdn/{msisdn}/assign"
        )
        return resp.json()

    async def release_msisdn(self, msisdn: str) -> dict[str, Any]:
        """POST /inventory-api/v1/msisdn/{msisdn}/release."""
        resp = await self._request(
            "POST", f"/inventory-api/v1/msisdn/{msisdn}/release"
        )
        return resp.json()

    # ── eSIM ────────────────────────────────────────────────────────

    async def get_esim(self, iccid: str) -> dict[str, Any]:
        """GET /inventory-api/v1/esim/{iccid}."""
        resp = await self._request(
            "GET", f"/inventory-api/v1/esim/{iccid}"
        )
        return resp.json()

    async def reserve_esim(self) -> dict[str, Any]:
        """POST /inventory-api/v1/esim/reserve."""
        resp = await self._request(
            "POST", "/inventory-api/v1/esim/reserve"
        )
        return resp.json()

    async def assign_msisdn_to_esim(
        self, iccid: str, msisdn: str
    ) -> dict[str, Any]:
        """POST /inventory-api/v1/esim/{iccid}/assign-msisdn."""
        resp = await self._request(
            "POST",
            f"/inventory-api/v1/esim/{iccid}/assign-msisdn",
            json={"msisdn": msisdn},
        )
        return resp.json()

    async def recycle_esim(self, iccid: str) -> dict[str, Any]:
        """POST /inventory-api/v1/esim/{iccid}/recycle."""
        resp = await self._request(
            "POST", f"/inventory-api/v1/esim/{iccid}/recycle"
        )
        return resp.json()
