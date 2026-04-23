"""Case thread drill-in — filled in at Step 7."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..deps import require_operator
from ..session import OperatorSession

router = APIRouter()


@router.get("/case/{case_id}", response_class=HTMLResponse)
async def case_thread(
    request: Request,
    case_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    return HTMLResponse(f"<p>scaffold — Step 7 fills /case/{case_id}</p>")
