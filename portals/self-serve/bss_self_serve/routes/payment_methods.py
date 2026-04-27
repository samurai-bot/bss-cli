"""``/payment-methods`` — card-on-file management (v0.10 PR 5).

V0_10_0.md Track 4:

* GET ``/payment-methods`` — list customer's methods, last-4 + brand,
  default toggle, "Add new" CTA.
* GET ``/payment-methods/add`` — Stripe-shaped form: card number,
  exp month/year, CVV, holder name, postal code. CVV + postal are
  ignored by the v0.10 mock provider; v1.0 (Stripe Elements) wires
  them through, the UX shape doesn't change.
* POST ``/payment-methods/add`` — step-up=``payment_method_add``;
  tokenize client-side (same sandbox pattern the orchestrator uses)
  + one ``payment.create_payment_method`` call.
* POST ``/payment-methods/<pm_id>/remove`` — step-up=``payment_method_remove``;
  ownership check; one ``payment.remove_method`` call. The
  service-side policy refuses to remove the only method while the
  customer has active lines.
* POST ``/payment-methods/<pm_id>/set-default`` —
  step-up=``payment_method_set_default``; ownership check; one
  ``payment.set_default_method`` call.

Doctrine:

* ``customer_id`` from ``request.state.customer_id``; ``pm_id`` from
  the URL path is checked for ownership against the customer's
  method list before any write.
* One BSS write per route. Tokenization is sandbox-side (no BSS
  write); the bss-clients call is the single write.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog
from bss_clients import PolicyViolationFromServer
from bss_portal_auth import IdentityView, record_portal_action
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..clients import get_clients
from ..error_messages import is_known, render
from ..security import (
    requires_linked_customer,
    requires_step_up,
)
from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


_OWNERSHIP_RULE = "policy.ownership.payment_method_not_owned"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _client_ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _identity_id(request: Request) -> str | None:
    identity: IdentityView | None = getattr(request.state, "identity", None)
    return identity.id if identity is not None else None


def _local_tokenize(card_number: str) -> dict[str, str]:
    """Client-side sandbox tokenizer.

    Mirrors the orchestrator's ``_local_tokenize`` so the v1.0 cutover
    to real Stripe.js / Adyen tokenization doesn't change the wire
    shape from the portal to the payment service. Embeds ``FAIL`` /
    ``DECLINE`` in the token so payment-side mock can simulate
    declines deterministically.
    """
    digits = card_number.replace(" ", "").replace("-", "")
    if not digits.isdigit() or len(digits) < 12:
        raise ValueError("Card number is invalid.")
    last4 = digits[-4:]
    bin2 = digits[:2]
    if digits[0] == "4":
        brand = "visa"
    elif 51 <= int(bin2) <= 55:
        brand = "mastercard"
    elif bin2 in ("34", "37"):
        brand = "amex"
    else:
        brand = "unknown"
    uid = str(uuid4())
    upper = card_number.upper()
    if "FAIL" in upper:
        token = f"tok_FAIL_{uid}"
    elif "DECLINE" in upper:
        token = f"tok_DECLINE_{uid}"
    else:
        token = f"tok_{uid}"
    return {"cardToken": token, "last4": last4, "brand": brand}


async def _list_owned(
    clients: Any, customer_id: str
) -> list[dict[str, Any]]:
    return await clients.payment.list_methods(customer_id)


async def _check_method_ownership(
    clients: Any, pm_id: str, customer_id: str
) -> dict[str, Any] | None:
    """Return the method dict iff it belongs to ``customer_id`` and is active.

    Same forensic posture as ``check_subscription_owned_by``: the
    customer-facing distinction between "doesn't exist" and "not
    yours" is intentional cover.
    """
    methods = await _list_owned(clients, customer_id)
    for m in methods:
        if m.get("id") == pm_id:
            return m
    return None


# ── GET /payment-methods ─────────────────────────────────────────────────


@router.get("/payment-methods", response_class=HTMLResponse)
async def list_methods(
    request: Request,
    customer_id: str = Depends(requires_linked_customer),
) -> Response:
    methods = await _list_owned(get_clients(), customer_id)
    return templates.TemplateResponse(
        request,
        "payment_methods.html",
        {"methods": methods, "error": None, "flash": None},
    )


# ── GET /payment-methods/add ─────────────────────────────────────────────


@router.get("/payment-methods/add", response_class=HTMLResponse)
async def add_method_form(
    request: Request,
    customer_id: str = Depends(requires_linked_customer),
) -> Response:
    return templates.TemplateResponse(
        request,
        "payment_methods_add.html",
        {"error": None, "fields": {}},
    )


# ── POST /payment-methods/add ────────────────────────────────────────────


@router.post("/payment-methods/add")
async def add_method(
    request: Request,
    card_number: str = Form(..., min_length=12),
    exp_month: int = Form(..., ge=1, le=12),
    exp_year: int = Form(..., ge=2026, le=2099),
    cvv: str = Form(..., min_length=3, max_length=4),  # noqa: ARG001 — Stripe-shaped seam
    holder_name: str = Form(..., min_length=1),  # noqa: ARG001 — surfaced in v1.0
    postal_code: str | None = Form(default=None),  # noqa: ARG001 — surfaced in v1.0
    customer_id: str = Depends(requires_linked_customer),
    _step_up: None = Depends(requires_step_up("payment_method_add")),
) -> Response:
    """Tokenize the card client-side, then one create_payment_method call."""
    clients = get_clients()
    factory = request.app.state.db_session_factory
    iid = _identity_id(request)

    try:
        tok = _local_tokenize(card_number)
    except ValueError as exc:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_add",
                route="/payment-methods/add",
                method="POST",
                success=False,
                error_rule="policy.payment.method.invalid_card",
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        return templates.TemplateResponse(
            request,
            "payment_methods_add.html",
            {
                "error": "That card number doesn't look right. Check the digits.",
                "fields": {"exp_month": exp_month, "exp_year": exp_year},
            },
            status_code=422,
        )

    try:
        await clients.payment.create_payment_method(
            customer_id=customer_id,
            card_token=tok["cardToken"],
            last4=tok["last4"],
            brand=tok["brand"],
            exp_month=exp_month,
            exp_year=exp_year,
        )
    except PolicyViolationFromServer as exc:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_add",
                route="/payment-methods/add",
                method="POST",
                success=False,
                error_rule=exc.rule,
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        if not is_known(exc.rule):
            log.info("portal.payment_methods.unknown_policy_rule", rule=exc.rule)
        return templates.TemplateResponse(
            request,
            "payment_methods_add.html",
            {
                "error": render(exc.rule),
                "fields": {"exp_month": exp_month, "exp_year": exp_year},
            },
            status_code=422,
        )

    async with factory() as db:
        await record_portal_action(
            db,
            customer_id=customer_id,
            identity_id=iid,
            action="payment_method_add",
            route="/payment-methods/add",
            method="POST",
            success=True,
            step_up_consumed=True,
            ip=_client_ip(request),
            user_agent=_client_ua(request),
        )
        await db.commit()

    return RedirectResponse(url="/payment-methods?flash=added", status_code=303)


# ── POST /payment-methods/<pm_id>/remove ─────────────────────────────────


@router.post("/payment-methods/{pm_id}/remove")
async def remove_method(
    request: Request,
    pm_id: str,
    customer_id: str = Depends(requires_linked_customer),
    _step_up: None = Depends(requires_step_up("payment_method_remove")),
) -> Response:
    clients = get_clients()
    factory = request.app.state.db_session_factory
    iid = _identity_id(request)

    owned = await _check_method_ownership(clients, pm_id, customer_id)
    if owned is None:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_remove",
                route=f"/payment-methods/{pm_id}/remove",
                method="POST",
                success=False,
                error_rule=_OWNERSHIP_RULE,
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        return templates.TemplateResponse(
            request,
            "payment_methods_forbidden.html",
            {"customer_facing": render(_OWNERSHIP_RULE)},
            status_code=403,
        )

    try:
        await clients.payment.remove_method(pm_id)
    except PolicyViolationFromServer as exc:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_remove",
                route=f"/payment-methods/{pm_id}/remove",
                method="POST",
                success=False,
                error_rule=exc.rule,
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        # Re-render the list with the structured error visible — the
        # canonical example here is "can't remove the only method
        # while you have an active line".
        methods = await _list_owned(clients, customer_id)
        return templates.TemplateResponse(
            request,
            "payment_methods.html",
            {"methods": methods, "error": render(exc.rule), "flash": None},
            status_code=422,
        )

    async with factory() as db:
        await record_portal_action(
            db,
            customer_id=customer_id,
            identity_id=iid,
            action="payment_method_remove",
            route=f"/payment-methods/{pm_id}/remove",
            method="POST",
            success=True,
            step_up_consumed=True,
            ip=_client_ip(request),
            user_agent=_client_ua(request),
        )
        await db.commit()

    return RedirectResponse(url="/payment-methods?flash=removed", status_code=303)


# ── POST /payment-methods/<pm_id>/set-default ────────────────────────────


@router.post("/payment-methods/{pm_id}/set-default")
async def set_default(
    request: Request,
    pm_id: str,
    customer_id: str = Depends(requires_linked_customer),
    _step_up: None = Depends(requires_step_up("payment_method_set_default")),
) -> Response:
    clients = get_clients()
    factory = request.app.state.db_session_factory
    iid = _identity_id(request)

    owned = await _check_method_ownership(clients, pm_id, customer_id)
    if owned is None:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_set_default",
                route=f"/payment-methods/{pm_id}/set-default",
                method="POST",
                success=False,
                error_rule=_OWNERSHIP_RULE,
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        return templates.TemplateResponse(
            request,
            "payment_methods_forbidden.html",
            {"customer_facing": render(_OWNERSHIP_RULE)},
            status_code=403,
        )

    try:
        await clients.payment.set_default_method(pm_id)
    except PolicyViolationFromServer as exc:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action="payment_method_set_default",
                route=f"/payment-methods/{pm_id}/set-default",
                method="POST",
                success=False,
                error_rule=exc.rule,
                step_up_consumed=True,
                ip=_client_ip(request),
                user_agent=_client_ua(request),
            )
            await db.commit()
        methods = await _list_owned(clients, customer_id)
        return templates.TemplateResponse(
            request,
            "payment_methods.html",
            {"methods": methods, "error": render(exc.rule), "flash": None},
            status_code=422,
        )

    async with factory() as db:
        await record_portal_action(
            db,
            customer_id=customer_id,
            identity_id=iid,
            action="payment_method_set_default",
            route=f"/payment-methods/{pm_id}/set-default",
            method="POST",
            success=True,
            step_up_consumed=True,
            ip=_client_ip(request),
            user_agent=_client_ua(request),
        )
        await db.commit()

    return RedirectResponse(url="/payment-methods?flash=default_set", status_code=303)
