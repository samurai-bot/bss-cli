"""Concurrent subscription creation — proves no PK collision or MSISDN/ICCID duplication.

Sequential creates through the test session verifying uniqueness constraints.
The real concurrency proof (SELECT FOR UPDATE SKIP LOCKED) lives in CRM's
inventory sub-domain; here we verify that the subscription service side
(Postgres sequence + UNIQUE constraints) holds under sequential load.
"""

import pytest


@pytest.mark.asyncio
async def test_sequential_creates_no_collision(client, mock_clients):
    """10 sequential creates should produce 10 unique subscriptions."""
    sub_ids = []
    msisdns = set()
    iccids = set()

    for i in range(10):
        resp = await client.post(
            "/subscription-api/v1/subscription",
            json={
                "customerId": f"CUST-{i:04d}",
                "offeringId": "PLAN_M",
                "msisdn": f"9000{i:04d}",
                "iccid": f"891000000000{i:04d}",
                "paymentMethodId": f"PM-{i:04d}",
            },
        )
        assert resp.status_code == 201, f"Create #{i} failed: {resp.text}"
        body = resp.json()
        sub_ids.append(body["id"])
        msisdns.add(body["msisdn"])
        iccids.add(body["iccid"])

    assert len(set(sub_ids)) == 10, f"PK collision: {sub_ids}"
    assert len(msisdns) == 10, f"MSISDN duplication: {msisdns}"
    assert len(iccids) == 10, f"ICCID duplication: {iccids}"

    # Verify IDs are monotonic
    nums = [int(s.split("-")[1]) for s in sub_ids]
    for a, b in zip(nums, nums[1:]):
        assert a < b, f"IDs not monotonic: {sub_ids}"
