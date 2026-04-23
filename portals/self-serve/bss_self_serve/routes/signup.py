"""Signup flow — GET form, POST triggers agent. Filled in at Steps 4-5."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/signup/{plan}")
async def signup_get(plan: str) -> dict:
    return {"page": "signup", "plan": plan, "status": "scaffold"}
