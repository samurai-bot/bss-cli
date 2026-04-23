"""Confirmation page — QR PNG + LPA code. Filled in at Step 6."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/confirmation/{subscription_id}")
async def confirmation(subscription_id: str) -> dict:
    return {"page": "confirmation", "subscription_id": subscription_id, "status": "scaffold"}
