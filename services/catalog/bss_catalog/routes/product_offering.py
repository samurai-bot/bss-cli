from fastapi import APIRouter, Depends, HTTPException

from bss_catalog.deps import get_repo
from bss_catalog.repository import CatalogRepository
from bss_catalog.schemas.tmf620 import Tmf620ProductOffering, to_tmf620_offering

router = APIRouter(tags=["productOffering"])


@router.get("/productOffering", response_model=list[Tmf620ProductOffering], response_model_by_alias=True)
async def list_offerings(
    lifecycleStatus: str | None = None,
    limit: int = 20,
    offset: int = 0,
    repo: CatalogRepository = Depends(get_repo),
) -> list[Tmf620ProductOffering]:
    models = await repo.list_offerings(
        lifecycle_status=lifecycleStatus,
        limit=limit,
        offset=offset,
    )
    return [to_tmf620_offering(m) for m in models]


@router.get("/productOffering/{offering_id}", response_model=Tmf620ProductOffering, response_model_by_alias=True)
async def get_offering(
    offering_id: str,
    repo: CatalogRepository = Depends(get_repo),
) -> Tmf620ProductOffering:
    model = await repo.get_offering(offering_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"ProductOffering {offering_id} not found")
    return to_tmf620_offering(model)
