"""PaymentClient — service-to-service client for Payment.

Scaffold for Phase 6 (Subscription calls payment.charge for renewal/VAS).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class PaymentClient(BSSClient):
    """Client for the Payment service (port 8003)."""

    def __init__(
        self,
        base_url: str = "http://payment:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    async def charge(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        amount: Decimal,
        currency: str = "SGD",
        purpose: str,
    ) -> dict[str, Any]:
        """POST /tmf-api/paymentManagement/v4/payment."""
        resp = await self._request(
            "POST",
            "/tmf-api/paymentManagement/v4/payment",
            json={
                "customerId": customer_id,
                "paymentMethodId": payment_method_id,
                "amount": str(amount),
                "currency": currency,
                "purpose": purpose,
            },
        )
        return resp.json()

    async def get_method(self, method_id: str) -> dict[str, Any]:
        """GET /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}."""
        resp = await self._request(
            "GET",
            f"/tmf-api/paymentMethodManagement/v4/paymentMethod/{method_id}",
        )
        return resp.json()

    async def list_methods(self, customer_id: str) -> list[dict[str, Any]]:
        """GET /tmf-api/paymentMethodManagement/v4/paymentMethod?customerId={id}."""
        resp = await self._request(
            "GET",
            "/tmf-api/paymentMethodManagement/v4/paymentMethod",
            params={"customerId": customer_id},
        )
        return resp.json()
