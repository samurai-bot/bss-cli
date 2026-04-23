"""Landing page — plan cards. Filled in at Step 4."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def landing() -> dict:
    # Placeholder — Step 4 replaces with a real Jinja-rendered plan grid.
    return {"page": "landing", "status": "scaffold — Step 4 fills this in"}
