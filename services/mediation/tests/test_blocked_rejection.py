"""Block-at-edge: rejected usage leaves zero usage_event rows but audits the attempt."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from bss_clients.errors import NotFound
from bss_models.audit import DomainEvent
from bss_models.mediation import UsageEvent
from sqlalchemy import select

USAGE_PATH = "/tmf-api/usageManagement/v4/usage"


def _payload(**overrides) -> dict:
    body = {
        "msisdn": "90000042",
        "eventType": "data",
        "eventTime": datetime.now(timezone.utc).isoformat(),
        "quantity": 100,
        "unit": "mb",
        "source": "test",
        "rawCdrRef": "CDR-BLOCK-0001",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_blocked_subscription_rejected_no_usage_row(client, mock_clients, db_session):
    mock_clients["subscription"].get_by_msisdn = AsyncMock(
        return_value={
            "id": "SUB-0042",
            "customerId": "CUST-0001",
            "offeringId": "PLAN_M",
            "msisdn": "90000042",
            "state": "blocked",
        }
    )

    resp = await client.post(USAGE_PATH, json=_payload(rawCdrRef="CDR-BLOCKED"))
    assert resp.status_code == 422
    assert resp.json()["reason"] == "usage.record.subscription_must_be_active"

    # No mediation.usage_event row for this CDR
    rows = await db_session.execute(
        select(UsageEvent).where(UsageEvent.raw_cdr_ref == "CDR-BLOCKED")
    )
    assert rows.scalars().all() == []

    # usage.rejected audit row was written
    audits = await db_session.execute(
        select(DomainEvent).where(DomainEvent.event_type == "usage.rejected")
    )
    rejected = audits.scalars().all()
    assert len(rejected) == 1
    assert rejected[0].payload["reason"] == "usage.record.subscription_must_be_active"
    assert rejected[0].payload["state"] == "blocked"
    assert rejected[0].aggregate_id == "SUB-0042"


@pytest.mark.asyncio
async def test_unknown_msisdn_rejected_no_usage_row(client, mock_clients, db_session):
    mock_clients["subscription"].get_by_msisdn = AsyncMock(side_effect=NotFound("no sub"))

    resp = await client.post(USAGE_PATH, json=_payload(msisdn="90000999", rawCdrRef="CDR-UNK"))
    assert resp.status_code == 422
    assert resp.json()["reason"] == "usage.record.subscription_must_exist"

    rows = await db_session.execute(
        select(UsageEvent).where(UsageEvent.raw_cdr_ref == "CDR-UNK")
    )
    assert rows.scalars().all() == []

    audits = await db_session.execute(
        select(DomainEvent).where(DomainEvent.event_type == "usage.rejected")
    )
    rejected = audits.scalars().all()
    assert len(rejected) == 1
    assert rejected[0].payload["reason"] == "usage.record.subscription_must_exist"


@pytest.mark.asyncio
async def test_happy_path_writes_usage_recorded_audit(client, db_session):
    resp = await client.post(USAGE_PATH, json=_payload(rawCdrRef="CDR-OK"))
    assert resp.status_code == 201

    audits = await db_session.execute(
        select(DomainEvent).where(DomainEvent.event_type == "usage.recorded")
    )
    recorded = audits.scalars().all()
    assert len(recorded) == 1
    assert recorded[0].payload["msisdn"] == "90000042"
    assert recorded[0].payload["subscriptionId"] == "SUB-0001"
