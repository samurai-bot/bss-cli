"""SubscriptionClient — service-to-service client for Subscription (port 8006)."""

from __future__ import annotations

from datetime import datetime
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
        price_snapshot: dict | None = None,
    ) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription — create and activate.

        v0.7 — `price_snapshot` carries the active price row captured at
        order-creation time. Required by COM in steady state; legacy direct
        callers can omit it and the service falls back to the catalog.
        """
        body: dict[str, Any] = {
            "customerId": customer_id,
            "offeringId": offering_id,
            "msisdn": msisdn,
            "iccid": iccid,
            "paymentMethodId": payment_method_id,
        }
        if price_snapshot is not None:
            body["priceSnapshot"] = price_snapshot
        resp = await self._request(
            "POST",
            "/subscription-api/v1/subscription",
            json=body,
        )
        return resp.json()

    async def get(self, subscription_id: str) -> dict[str, Any]:
        """GET /subscription-api/v1/subscription/{id}."""
        resp = await self._request(
            "GET", f"/subscription-api/v1/subscription/{subscription_id}"
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
            "GET", f"/subscription-api/v1/subscription/by-msisdn/{msisdn}"
        )
        return resp.json()

    async def get_balance(self, subscription_id: str) -> dict[str, Any]:
        """GET /subscription-api/v1/subscription/{id}/balance."""
        resp = await self._request(
            "GET", f"/subscription-api/v1/subscription/{subscription_id}/balance"
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

    async def renew(self, subscription_id: str) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription/{id}/renew — manual renewal."""
        resp = await self._request(
            "POST", f"/subscription-api/v1/subscription/{subscription_id}/renew"
        )
        return resp.json()

    async def terminate(
        self, subscription_id: str, *, reason: str | None = None
    ) -> dict[str, Any]:
        """POST /subscription-api/v1/subscription/{id}/terminate — destructive.

        ``reason`` is forensic only (carried into the state-history row
        + ``subscription.terminated`` event). Server defaults to
        ``"customer_requested"`` when the body is empty, preserving
        backwards compatibility with v0.x callers that pass no body.
        v0.10 portal cancel route passes ``"customer_requested"``.
        """
        body = {"reason": reason} if reason is not None else None
        resp = await self._request(
            "POST",
            f"/subscription-api/v1/subscription/{subscription_id}/terminate",
            json=body,
        )
        return resp.json()

    # ── v0.7 — plan change ─────────────────────────────────────────────

    async def schedule_plan_change(
        self, subscription_id: str, new_offering_id: str
    ) -> dict[str, Any]:
        """POST /subscription/{id}/schedule-plan-change — applies at next renewal."""
        resp = await self._request(
            "POST",
            f"/subscription-api/v1/subscription/{subscription_id}/schedule-plan-change",
            json={"newOfferingId": new_offering_id},
        )
        return resp.json()

    async def cancel_plan_change(self, subscription_id: str) -> dict[str, Any]:
        """POST /subscription/{id}/cancel-plan-change — clears pending fields."""
        resp = await self._request(
            "POST",
            f"/subscription-api/v1/subscription/{subscription_id}/cancel-plan-change",
        )
        return resp.json()

    async def migrate_to_new_price(
        self,
        *,
        offering_id: str,
        new_price_id: str,
        effective_from: datetime,
        notice_days: int = 30,
        initiated_by: str,
    ) -> dict[str, Any]:
        """POST /admin/subscription/migrate-price — operator price migration.

        Schedules the new price for every active subscription on
        ``offering_id``. Returns ``{count, subscriptionIds}``.
        Admin-only on the server side.
        """
        resp = await self._request(
            "POST",
            "/subscription-api/v1/admin/subscription/migrate-price",
            json={
                "offeringId": offering_id,
                "newPriceId": new_price_id,
                "effectiveFrom": effective_from.isoformat(),
                "noticeDays": notice_days,
                "initiatedBy": initiated_by,
            },
        )
        return resp.json()

    async def get_esim_activation(self, subscription_id: str) -> dict[str, Any]:
        """Resolve the eSIM activation payload for a subscription.

        Convenience: reads the subscription, extracts its iccid, then fetches
        the activation-code record from Inventory. Caller typically wants
        {iccid, imsi, activationCode, msisdn} for first-time QR display.
        """
        sub = await self.get(subscription_id)
        return {
            "subscriptionId": subscription_id,
            "iccid": sub.get("iccid"),
            "msisdn": sub.get("msisdn"),
            "activationCode": sub.get("activationCode"),
            "imsi": sub.get("imsi"),
        }
