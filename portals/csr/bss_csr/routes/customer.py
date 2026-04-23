"""Customer 360 view — filled in at Step 5."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..deps import require_operator
from ..session import OperatorSession

router = APIRouter()


@router.get("/customer/{customer_id}", response_class=HTMLResponse)
async def customer_360(
    request: Request,
    customer_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    return HTMLResponse(f"<p>scaffold — Step 5 fills /customer/{customer_id}</p>")
