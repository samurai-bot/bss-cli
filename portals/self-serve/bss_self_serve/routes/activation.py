"""Activation progress page — polls order.get. Filled in at Step 6."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/activation/{order_id}")
async def activation(order_id: str) -> dict:
    return {"page": "activation", "order_id": order_id, "status": "scaffold"}
