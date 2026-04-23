"""Search page — filled in at Step 5."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..deps import require_operator
from ..session import OperatorSession
from ..templating import templates

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = "",
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    # Placeholder — Step 5 fills with real CRM/inventory lookups.
    return templates.TemplateResponse(
        request,
        "search.html",
        {"operator": operator, "q": q, "results": []},
    )
