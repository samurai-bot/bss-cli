"""v0.7 — CatalogClient active-aware methods."""

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from bss_clients import CatalogClient, PolicyViolationFromServer

BASE_URL = "http://catalog:8000"


@pytest.fixture
def client():
    return CatalogClient(base_url=BASE_URL)


class TestListActiveOfferings:
    @pytest.mark.asyncio
    @respx.mock
    async def test_explicit_at_passes_iso(self, client):
        moment = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
        route = respx.get(
            f"{BASE_URL}/tmf-api/productCatalogManagement/v4/productOffering"
        ).mock(return_value=Response(200, json=[]))
        await client.list_active_offerings(at=moment)
        called = route.calls.last.request
        assert "activeAt=2026-02-15T12%3A00%3A00%2B00%3A00" in str(called.url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_default_at_sends_clock_now(self, client):
        route = respx.get(
            f"{BASE_URL}/tmf-api/productCatalogManagement/v4/productOffering"
        ).mock(return_value=Response(200, json=[]))
        await client.list_active_offerings()
        # bss_clock.now() is called — we don't assert the exact value, just that
        # an activeAt parameter was sent.
        assert "activeAt=" in str(route.calls.last.request.url)


class TestGetActivePrice:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_price_dict(self, client):
        respx.get(
            f"{BASE_URL}/tmf-api/productCatalogManagement/v4/productOfferingPrice/active/PLAN_M"
        ).mock(return_value=Response(200, json={"id": "PRICE_PLAN_M"}))
        result = await client.get_active_price("PLAN_M")
        assert result["id"] == "PRICE_PLAN_M"

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_active_row_raises_policy_violation(self, client):
        body = {
            "code": "POLICY_VIOLATION",
            "reason": "catalog.price.no_active_row",
            "message": "No active recurring price for offering PLAN_X",
            "context": {"offering_id": "PLAN_X"},
        }
        respx.get(
            f"{BASE_URL}/tmf-api/productCatalogManagement/v4/productOfferingPrice/active/PLAN_X"
        ).mock(return_value=Response(422, json=body))
        with pytest.raises(PolicyViolationFromServer) as exc_info:
            await client.get_active_price("PLAN_X")
        assert exc_info.value.rule == "catalog.price.no_active_row"


class TestGetOfferingPriceById:
    @pytest.mark.asyncio
    @respx.mock
    async def test_direct_lookup(self, client):
        respx.get(
            f"{BASE_URL}/tmf-api/productCatalogManagement/v4/productOfferingPrice/PRICE_PLAN_M"
        ).mock(return_value=Response(200, json={"id": "PRICE_PLAN_M"}))
        result = await client.get_offering_price("PRICE_PLAN_M")
        assert result["id"] == "PRICE_PLAN_M"
