"""BillingClient — service-to-service client for Billing (port 8009).

The Billing service is a stub in v0.1 — no routers implemented yet.
This client exists so the orchestrator's tool surface can be wired end-to-end;
calls will raise on the network layer until the service is fleshed out in Phase 10.
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class BillingClient(BSSClient):
    """Client for the Billing service (port 8009) — stub in v0.1."""

    def __init__(
        self,
        base_url: str = "http://billing:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    async def list_bills(
        self, *, customer_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """GET /tmf-api/customerBillManagement/v4/customerBill — not implemented in v0.1."""
        resp = await self._request(
            "GET",
            "/tmf-api/customerBillManagement/v4/customerBill",
            params={"customerId": customer_id, "limit": limit},
        )
        return resp.json()

    async def get_bill(self, bill_id: str) -> dict[str, Any]:
        """GET /tmf-api/customerBillManagement/v4/customerBill/{id} — not implemented in v0.1."""
        resp = await self._request(
            "GET",
            f"/tmf-api/customerBillManagement/v4/customerBill/{bill_id}",
        )
        return resp.json()
