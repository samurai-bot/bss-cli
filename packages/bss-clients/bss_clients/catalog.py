"""CatalogClient — service-to-service client for Catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bss_clock import now as clock_now

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

    async def list_active_offerings(
        self, *, at: datetime | None = None
    ) -> list[dict[str, Any]]:
        """GET /productOffering?activeAt=ISO — sellable-now offerings, sorted by lowest price."""
        moment = at or clock_now()
        resp = await self._request(
            "GET",
            "/tmf-api/productCatalogManagement/v4/productOffering",
            params={"activeAt": moment.isoformat()},
        )
        return resp.json()

    async def get_active_price(
        self, offering_id: str, *, at: datetime | None = None
    ) -> dict[str, Any]:
        """GET /productOfferingPrice/active/{offering_id}?activeAt=ISO.

        Raises ``PolicyViolationFromServer('catalog.price.no_active_row')``
        when no row matches at the requested moment.
        """
        params: dict[str, Any] = {}
        if at is not None:
            params["activeAt"] = at.isoformat()
        resp = await self._request(
            "GET",
            f"/tmf-api/productCatalogManagement/v4/productOfferingPrice/active/{offering_id}",
            params=params,
        )
        return resp.json()

    async def get_offering_price(self, price_id: str) -> dict[str, Any]:
        """GET /productOfferingPrice/{id} — direct lookup, no time filter."""
        resp = await self._request(
            "GET",
            f"/tmf-api/productCatalogManagement/v4/productOfferingPrice/{price_id}",
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

    # ── v0.7 — admin write paths ───────────────────────────────────────

    async def admin_add_offering(
        self,
        *,
        offering_id: str,
        name: str,
        amount: str,
        currency: str = "SGD",
        spec_id: str = "SPEC_MOBILE_PREPAID",
        price_id: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        data_mb: int | None = None,
        voice_minutes: int | None = None,
        sms_count: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "offeringId": offering_id,
            "name": name,
            "specId": spec_id,
            "amount": amount,
            "currency": currency,
        }
        if price_id is not None:
            body["priceId"] = price_id
        if valid_from is not None:
            body["validFrom"] = valid_from.isoformat()
        if valid_to is not None:
            body["validTo"] = valid_to.isoformat()
        if data_mb is not None:
            body["dataMb"] = data_mb
        if voice_minutes is not None:
            body["voiceMinutes"] = voice_minutes
        if sms_count is not None:
            body["smsCount"] = sms_count
        resp = await self._request("POST", "/admin/catalog/offering", json=body)
        return resp.json()

    async def admin_set_offering_window(
        self,
        offering_id: str,
        *,
        valid_from: datetime | None,
        valid_to: datetime | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if valid_from is not None:
            body["validFrom"] = valid_from.isoformat()
        if valid_to is not None:
            body["validTo"] = valid_to.isoformat()
        resp = await self._request(
            "PATCH",
            f"/admin/catalog/offering/{offering_id}/window",
            json=body,
        )
        return resp.json()

    async def admin_add_price(
        self,
        offering_id: str,
        *,
        price_id: str,
        amount: str,
        currency: str = "SGD",
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        retire_current: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "priceId": price_id,
            "amount": amount,
            "currency": currency,
            "retireCurrent": retire_current,
        }
        if valid_from is not None:
            body["validFrom"] = valid_from.isoformat()
        if valid_to is not None:
            body["validTo"] = valid_to.isoformat()
        resp = await self._request(
            "POST",
            f"/admin/catalog/offering/{offering_id}/price",
            json=body,
        )
        return resp.json()


