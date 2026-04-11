"""CRMClient — service-to-service client for CRM.

Used by Payment (Phase 5) for customer_exists policy check.
Used by COM (Phase 6) for customer lookup and KYC status.
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class CRMClient(BSSClient):
    """Client for the CRM service (port 8002)."""

    def __init__(
        self,
        base_url: str = "http://crm:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """GET /tmf-api/customerManagement/v4/customer/{id}.

        Returns the TMF629 customer payload.
        Raises NotFound if customer does not exist.
        """
        resp = await self._request(
            "GET",
            f"/tmf-api/customerManagement/v4/customer/{customer_id}",
        )
        return resp.json()
