"""Test SOM decomposition logic."""

from unittest.mock import AsyncMock

import pytest

from app.repositories.service_order_repo import ServiceOrderRepository
from app.repositories.service_repo import ServiceRepository
from app.services.som_service import SOMService


async def test_decompose_creates_service_graph(client, db_session):
    """Decomposition should create SO -> CFS -> 2 RFS with reserved inventory."""
    app = client._transport.app
    svc = SOMService(
        session=db_session,
        so_repo=ServiceOrderRepository(db_session),
        svc_repo=ServiceRepository(db_session),
        inventory_client=app.state.inventory_client,
        exchange=None,
    )

    so = await svc.decompose(
        commercial_order_id="ORD-TEST-001",
        customer_id="CUST-0001",
        offering_id="PLAN_M",
        msisdn_preference=None,
        payment_method_id="PM-0001",
    )

    assert so.id.startswith("SO-")
    assert so.state == "in_progress"
    assert so.commercial_order_id == "ORD-TEST-001"

    # Verify inventory was reserved
    inv = app.state.inventory_client
    inv.reserve_next_msisdn.assert_called_once()
    inv.reserve_esim.assert_called_once()


async def test_decompose_rolls_back_msisdn_on_esim_failure(client, db_session):
    """If eSIM reservation fails, MSISDN must be released."""
    app = client._transport.app
    inv = app.state.inventory_client
    inv.reserve_esim = AsyncMock(side_effect=Exception("eSIM pool exhausted"))

    svc = SOMService(
        session=db_session,
        so_repo=ServiceOrderRepository(db_session),
        svc_repo=ServiceRepository(db_session),
        inventory_client=inv,
        exchange=None,
    )

    with pytest.raises(Exception, match="eSIM pool exhausted"):
        await svc.decompose(
            commercial_order_id="ORD-TEST-002",
            customer_id="CUST-0001",
            offering_id="PLAN_M",
            msisdn_preference=None,
            payment_method_id="PM-0001",
        )

    # MSISDN should have been released in rollback
    inv.release_msisdn.assert_called_once_with("90000042")
