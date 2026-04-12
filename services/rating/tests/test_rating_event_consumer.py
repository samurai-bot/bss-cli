"""Event consumer logic — usage.recorded → usage.rated.

The MQ wiring is tested via the helper `_handle_usage_recorded` directly,
with a mocked CatalogClient and an in-memory exchange stub.
"""

from unittest.mock import AsyncMock

import pytest
from app.domain.rating import RatingError
from app.events.consumer import _handle_usage_recorded
from bss_models.audit import DomainEvent
from sqlalchemy import select

PLAN_M_TARIFF = {
    "id": "PLAN_M",
    "bundleAllowance": [
        {"allowanceType": "data", "quantity": 30720, "unit": "mb"},
        {"allowanceType": "voice", "quantity": -1, "unit": "minutes"},
    ],
    "productOfferingPrice": [
        {"priceType": "recurring", "price": {"taxIncludedAmount": {"value": "25.00", "unit": "SGD"}}},
    ],
}


class _ExchangeStub:
    """Captures publishes to MQ in tests."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, message, routing_key: str):
        import json

        self.published.append((routing_key, json.loads(message.body.decode())))


@pytest.mark.asyncio
async def test_handle_usage_recorded_emits_usage_rated(db_session):
    catalog = AsyncMock()
    catalog.get_offering = AsyncMock(return_value=PLAN_M_TARIFF)
    exchange = _ExchangeStub()

    body = {
        "usageEventId": "UE-000001",
        "subscriptionId": "SUB-0001",
        "msisdn": "90000042",
        "eventType": "data",
        "quantity": 1000,
        "unit": "mb",
        "offeringId": "PLAN_M",
    }

    await _handle_usage_recorded(
        body,
        session=db_session,
        catalog_client=catalog,
        exchange=exchange,
    )

    # MQ published usage.rated
    assert len(exchange.published) == 1
    rk, payload = exchange.published[0]
    assert rk == "usage.rated"
    assert payload["subscriptionId"] == "SUB-0001"
    assert payload["allowanceType"] == "data"
    assert payload["consumedQuantity"] == 1000
    assert payload["chargeAmount"] == "0"

    # Audit row written
    await db_session.flush()
    rows = await db_session.execute(
        select(DomainEvent).where(DomainEvent.event_type == "usage.rated")
    )
    audits = rows.scalars().all()
    assert len(audits) == 1
    assert audits[0].aggregate_id == "UE-000001"
    assert audits[0].payload["allowanceType"] == "data"


@pytest.mark.asyncio
async def test_handle_usage_recorded_missing_offering_id_raises(db_session):
    catalog = AsyncMock()
    exchange = _ExchangeStub()

    body = {
        "usageEventId": "UE-000002",
        "subscriptionId": "SUB-0001",
        "msisdn": "90000042",
        "eventType": "data",
        "quantity": 1,
        "unit": "mb",
    }

    with pytest.raises(RatingError, match="missing offeringId"):
        await _handle_usage_recorded(
            body,
            session=db_session,
            catalog_client=catalog,
            exchange=exchange,
        )
    catalog.get_offering.assert_not_called()
    assert exchange.published == []


@pytest.mark.asyncio
async def test_handle_usage_recorded_tariff_without_allowance_raises(db_session):
    catalog = AsyncMock()
    catalog.get_offering = AsyncMock(
        return_value={"id": "PLAN_X", "bundleAllowance": []}
    )
    exchange = _ExchangeStub()

    body = {
        "usageEventId": "UE-000003",
        "subscriptionId": "SUB-0001",
        "msisdn": "90000042",
        "eventType": "data",
        "quantity": 1,
        "unit": "mb",
        "offeringId": "PLAN_X",
    }

    with pytest.raises(RatingError):
        await _handle_usage_recorded(
            body,
            session=db_session,
            catalog_client=catalog,
            exchange=exchange,
        )
    assert exchange.published == []
