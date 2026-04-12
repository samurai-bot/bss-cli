"""MSISDN pool endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_inventory_service
from app.schemas.internal.inventory import MsisdnResponse, to_msisdn_response
from app.services.inventory_service import InventoryService

router = APIRouter(tags=["Inventory MSISDN"])


@router.get("/msisdn", response_model=list[MsisdnResponse])
async def list_msisdns(
    status: str | None = None,
    prefix: str | None = None,
    limit: int = 20,
    offset: int = 0,
    svc: InventoryService = Depends(get_inventory_service),
) -> list[MsisdnResponse]:
    rows = await svc.list_msisdns(status=status, prefix=prefix, limit=limit, offset=offset)
    return [to_msisdn_response(r) for r in rows]


@router.get("/msisdn/{msisdn}", response_model=MsisdnResponse)
async def get_msisdn(
    msisdn: str,
    svc: InventoryService = Depends(get_inventory_service),
) -> MsisdnResponse:
    row = await svc.get_msisdn(msisdn)
    if not row:
        raise HTTPException(status_code=404, detail=f"MSISDN {msisdn} not found")
    return to_msisdn_response(row)


@router.post("/msisdn/{msisdn}/reserve", response_model=MsisdnResponse)
async def reserve_msisdn(
    msisdn: str,
    svc: InventoryService = Depends(get_inventory_service),
) -> MsisdnResponse:
    row = await svc.reserve_msisdn(msisdn)
    return to_msisdn_response(row)


@router.post("/msisdn/reserve-next", response_model=MsisdnResponse, status_code=201)
async def reserve_next_msisdn(
    body: dict | None = None,
    svc: InventoryService = Depends(get_inventory_service),
) -> MsisdnResponse:
    preference = (body or {}).get("preference")
    row = await svc.reserve_next_msisdn(preference=preference)
    return to_msisdn_response(row)


@router.post("/msisdn/{msisdn}/assign", response_model=MsisdnResponse)
async def assign_msisdn(
    msisdn: str,
    svc: InventoryService = Depends(get_inventory_service),
) -> MsisdnResponse:
    row = await svc.assign_msisdn(msisdn)
    return to_msisdn_response(row)


@router.post("/msisdn/{msisdn}/release", response_model=MsisdnResponse)
async def release_msisdn(
    msisdn: str,
    svc: InventoryService = Depends(get_inventory_service),
) -> MsisdnResponse:
    row = await svc.release_msisdn(msisdn)
    return to_msisdn_response(row)
