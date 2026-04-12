"""PaymentClient — service-to-service client for Payment (port 8003)."""

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

    # ── Payment attempts ────────────────────────────────────────────────

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

    async def get_payment(self, attempt_id: str) -> dict[str, Any]:
        """GET /tmf-api/paymentManagement/v4/payment/{attempt_id}."""
        resp = await self._request(
            "GET", f"/tmf-api/paymentManagement/v4/payment/{attempt_id}"
        )
        return resp.json()

    async def list_payments(
        self,
        *,
        customer_id: str | None = None,
        payment_method_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """GET /tmf-api/paymentManagement/v4/payment."""
        params: dict[str, Any] = {"limit": limit}
        if customer_id:
            params["customerId"] = customer_id
        if payment_method_id:
            params["paymentMethodId"] = payment_method_id
        resp = await self._request(
            "GET", "/tmf-api/paymentManagement/v4/payment", params=params
        )
        return resp.json()

    # ── Payment methods ─────────────────────────────────────────────────

    async def create_payment_method(
        self,
        *,
        customer_id: str,
        card_token: str,
        last4: str,
        brand: str,
        exp_month: int | None = None,
        exp_year: int | None = None,
    ) -> dict[str, Any]:
        """POST /tmf-api/paymentMethodManagement/v4/paymentMethod.

        Server is pre-tokenized (no PAN on the wire).
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "cardToken": card_token,
            "last4": last4,
            "brand": brand,
        }
        if exp_month is not None:
            body["expMonth"] = exp_month
        if exp_year is not None:
            body["expYear"] = exp_year
        resp = await self._request(
            "POST",
            "/tmf-api/paymentMethodManagement/v4/paymentMethod",
            json=body,
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
        """GET /tmf-api/paymentMethodManagement/v4/paymentMethod."""
        resp = await self._request(
            "GET",
            "/tmf-api/paymentMethodManagement/v4/paymentMethod",
            params={"customerId": customer_id},
        )
        return resp.json()

    async def remove_method(self, method_id: str) -> dict[str, Any]:
        """DELETE /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}."""
        resp = await self._request(
            "DELETE",
            f"/tmf-api/paymentMethodManagement/v4/paymentMethod/{method_id}",
        )
        return resp.json() if resp.content else {"id": method_id, "removed": True}

    # ── Dev tokenizer ────────────────────────────────────────────────────

    async def dev_tokenize_card(self, card_number: str) -> dict[str, Any]:
        """POST /dev/tokenize — dev-only tokenizer (sandbox).

        Returns {cardToken, last4, brand}. Used by the CLI to tokenize the
        user-supplied PAN before calling create_payment_method.
        """
        resp = await self._request(
            "POST",
            "/dev/tokenize",
            json={"cardNumber": card_number},
        )
        return resp.json()
