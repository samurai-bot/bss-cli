"""SubscriptionClient — service-to-service client for Subscription.

Used by CRM (customer.close policy) and future services (Mediation, Billing).
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class SubscriptionClient(BSSClient):
    """Client for the Subscription service (port 8006)."""

    def __init__(
        self,
        base_url: str = "http://subscription:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    async def create(
        self,
        *,
        customer_id: str,
        offering_id: str,
        msisdn: str,
        iccid: str,
        payment_method_id: str,
    ) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription — create and activate."""
        resp = await self._request(
            "POST",
            "/subscription-api/v1/subscription",
            json={
                "customerId": customer_id,
                "offeringId": offering_id,
                "msisdn": msisdn,
                "iccid": iccid,
                "paymentMethodId": payment_method_id,
            },
        )
        return resp.json()

    async def get(self, subscription_id: str) -> dict[str, Any]:
        """GET /subscription-api/v1/subscription/{id}."""
        resp = await self._request(
            "GET",
            f"/subscription-api/v1/subscription/{subscription_id}",
        )
        return resp.json()

    async def list_for_customer(self, customer_id: str) -> list[dict[str, Any]]:
        """GET /subscription-api/v1/subscription?customerId={id}."""
        resp = await self._request(
            "GET",
            "/subscription-api/v1/subscription",
            params={"customerId": customer_id},
        )
        return resp.json()

    async def get_by_msisdn(self, msisdn: str) -> dict[str, Any]:
        """GET /subscription-api/v1/subscription/by-msisdn/{msisdn}."""
        resp = await self._request(
            "GET",
            f"/subscription-api/v1/subscription/by-msisdn/{msisdn}",
        )
        return resp.json()

    async def purchase_vas(
        self, subscription_id: str, vas_offering_id: str
    ) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription/{id}/vas-purchase."""
        resp = await self._request(
            "POST",
            f"/subscription-api/v1/subscription/{subscription_id}/vas-purchase",
            json={"vasOfferingId": vas_offering_id},
        )
        return resp.json()

    async def terminate(self, subscription_id: str) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription/{id}/terminate."""
        resp = await self._request(
            "POST",
            f"/subscription-api/v1/subscription/{subscription_id}/terminate",
        )
        return resp.json()
