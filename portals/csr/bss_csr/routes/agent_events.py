"""GET /agent/events/{session_id} — filled in at Step 6."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..deps import require_operator
from ..session import OperatorSession

router = APIRouter()


@router.get("/agent/events/{session_id}")
async def agent_events(
    session_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> JSONResponse:
    return JSONResponse({"sse": "scaffold — Step 6 fills with streaming response"})
