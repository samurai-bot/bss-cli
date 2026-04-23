"""Search — name fragment OR full MSISDN.

If the query parses as a phone number (digits + optional +), redirect
straight to the customer 360 of the owning customer (single hit, no
intermediate page). Otherwise fall back to a name LIKE filter via
``customer.list``.
"""

from __future__ import annotations

from bss_clients.errors import ClientError
from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..deps import require_operator
from ..session import OperatorSession
from ..templating import templates
from ..views import flatten_customer, looks_like_msisdn

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = "",
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    q_clean = q.strip()
    results: list[dict] = []

    if q_clean and looks_like_msisdn(q_clean):
        # Try MSISDN lookup; jump straight to the customer 360 on a hit.
        digits = q_clean.lstrip("+").replace(" ", "")
        try:
            customer_raw = await get_clients().crm.find_customer_by_msisdn(digits)
        except ClientError:
            customer_raw = None
        if customer_raw:
            return RedirectResponse(
                url=f"/customer/{customer_raw['id']}",
                status_code=303,
            )
        # Fall through to render an empty results page for visibility.

    if q_clean and not looks_like_msisdn(q_clean):
        raw = await get_clients().crm.list_customers(name_contains=q_clean)
        results = [flatten_customer(c) for c in raw]

    return templates.TemplateResponse(
        request,
        "search.html",
        {"operator": operator, "q": q_clean, "results": results},
    )
