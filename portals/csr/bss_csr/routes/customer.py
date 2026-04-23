"""Customer 360 view — read-only assembly.

Fetches the 6 sections in parallel via ``asyncio.gather`` and renders
them. Subscription cards include balances, which means an N+1 hop
(``list_for_customer`` for the IDs, then ``get`` per subscription for
the balances roll-up). Typical customer = 1 subscription, so fine.

The agent never enters this path — reads go direct via bss-clients.
"""

from __future__ import annotations

import asyncio

from bss_clients.errors import ClientError
from bss_orchestrator.clients import get_clients
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..deps import require_operator
from ..session import OperatorSession
from ..templating import templates
from ..views import (
    flatten_case,
    flatten_customer,
    flatten_interaction,
    flatten_payment_method,
    flatten_subscription,
)

router = APIRouter()


async def _load_sections(customer_id: str) -> dict:
    clients = get_clients()

    async def _customer():
        try:
            return await clients.crm.get_customer(customer_id)
        except ClientError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def _subscriptions():
        try:
            stubs = await clients.subscription.list_for_customer(customer_id)
        except ClientError:
            return []
        # Re-fetch each by id so balances are populated (list endpoint
        # returns the headline shape; balances live under .get).
        if not stubs:
            return []
        full = await asyncio.gather(
            *(clients.subscription.get(s["id"]) for s in stubs),
            return_exceptions=True,
        )
        return [s for s in full if isinstance(s, dict)]

    async def _cases():
        try:
            return await clients.crm.list_cases(customer_id=customer_id)
        except ClientError:
            return []

    async def _payments():
        try:
            return await clients.payment.list_methods(customer_id=customer_id)
        except ClientError:
            return []

    async def _interactions():
        try:
            return await clients.crm.list_interactions(
                customer_id=customer_id, limit=20
            )
        except ClientError:
            return []

    customer, subs, cases, payments, interactions = await asyncio.gather(
        _customer(),
        _subscriptions(),
        _cases(),
        _payments(),
        _interactions(),
    )
    return {
        "customer": customer,
        "subscriptions": subs,
        "cases": cases,
        "payments": payments,
        "interactions": interactions,
    }


@router.get("/customer/{customer_id}", response_class=HTMLResponse)
async def customer_360(
    request: Request,
    customer_id: str,
    session: str | None = None,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    sections = await _load_sections(customer_id)
    if sections["customer"] is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return templates.TemplateResponse(
        request,
        "customer_360.html",
        {
            "operator": operator,
            "customer_id": customer_id,
            # When ?session=... is present, base.html attaches the SSE
            # connection. The 4 auto-refresh sections trigger on
            # ``sse:agent-complete from:body``; they swap on every
            # finished agent turn.
            "session_id": session,
            "stream_live": bool(session),
            "customer": flatten_customer(sections["customer"]),
            "subscriptions": [flatten_subscription(s) for s in sections["subscriptions"]],
            "cases": [flatten_case(c) for c in sections["cases"]],
            "payments": [flatten_payment_method(p) for p in sections["payments"]],
            "interactions": [flatten_interaction(i) for i in sections["interactions"]],
        },
    )


# Auto-refresh partials — Step 7 wires these into the SSE-triggered swap.
# Each returns just the section's HTML fragment, no <body>/<head>.


@router.get("/customer/{customer_id}/summary", response_class=HTMLResponse)
async def customer_summary_partial(
    request: Request,
    customer_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    sections = await _load_sections(customer_id)
    if sections["customer"] is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/customer_summary.html",
        {"customer": flatten_customer(sections["customer"])},
    )


@router.get("/customer/{customer_id}/subscriptions", response_class=HTMLResponse)
async def subscriptions_partial(
    request: Request,
    customer_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    sections = await _load_sections(customer_id)
    return templates.TemplateResponse(
        request,
        "partials/subscriptions_list.html",
        {
            "customer_id": customer_id,
            "subscriptions": [flatten_subscription(s) for s in sections["subscriptions"]],
        },
    )


@router.get("/customer/{customer_id}/cases", response_class=HTMLResponse)
async def cases_partial(
    request: Request,
    customer_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    sections = await _load_sections(customer_id)
    return templates.TemplateResponse(
        request,
        "partials/cases_list.html",
        {
            "customer_id": customer_id,
            "cases": [flatten_case(c) for c in sections["cases"]],
        },
    )


@router.get("/customer/{customer_id}/interactions", response_class=HTMLResponse)
async def interactions_partial(
    request: Request,
    customer_id: str,
    operator: OperatorSession = Depends(require_operator),
) -> HTMLResponse:
    sections = await _load_sections(customer_id)
    return templates.TemplateResponse(
        request,
        "partials/interactions_list.html",
        {
            "customer_id": customer_id,
            "interactions": [flatten_interaction(i) for i in sections["interactions"]],
        },
    )
