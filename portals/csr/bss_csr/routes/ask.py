"""POST /customer/{id}/ask — filled in at Step 6."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ..deps import require_operator
from ..session import OperatorSession

router = APIRouter()


@router.post("/customer/{customer_id}/ask")
async def ask(
    request: Request,
    customer_id: str,
    question: str = Form(...),
    operator: OperatorSession = Depends(require_operator),
) -> RedirectResponse:
    return RedirectResponse(url=f"/customer/{customer_id}", status_code=303)
