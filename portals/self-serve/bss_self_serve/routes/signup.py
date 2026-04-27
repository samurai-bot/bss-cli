"""Signup form + direct-write chain (v0.11+).

v0.4 ran the signup chain through the LLM orchestrator (one streaming
agent call drove every tool invocation through SSE). v0.11 replaces
that with a deterministic direct-API chain: each of the five steps is
its own route, each route makes exactly one ``bss-clients`` call, and
the progress page chains them via HTMX ``hx-post`` triggers. Wall time
drops from ~85s to under 10s because no LLM round-trips happen on the
signup path.

Step routes (one BSS write or zero per route):

* ``POST /signup``            — ``crm.create_customer`` (+ portal-auth
                                 ``link_to_customer`` to bind identity)
* ``POST /signup/step/kyc``   — ``crm.attest_kyc``
* ``POST /signup/step/cof``   — ``payment.create_payment_method``
                                 (PAN tokenized client-side, same
                                 sandbox tokenizer as the v0.10
                                 ``/payment-methods/add`` route)
* ``POST /signup/step/order`` — ``com.create_order`` + ``submit_order``
                                 (the orchestrator's ``order.create``
                                 tool wraps the same two calls; the
                                 service-side workflow is one
                                 conceptual write)
* ``GET /signup/step/poll``   — ``com.get_order`` (read-only). When
                                 ``state == completed`` and the
                                 subscription id is known, emits
                                 ``HX-Redirect`` to ``/confirmation``.

Doctrine (V0_11_0.md + CLAUDE.md ``(v0.11+ / chat only)``):

* No orchestrator imports. The signup routes are no longer in the
  carve-out whitelist for ``rg`` against the orchestrator entrypoint
  identifier under ``portals/self-serve/bss_self_serve/routes/``; the
  only orchestrator-mediated route is ``/chat`` (when it lands).
* ``request.state.identity`` is the only source of email and
  identity_id. The form never carries ``email`` server-side.
* ``portal_action`` audit row per write step (label from
  ``SIGNUP_ACTION_LABELS``); success and failure both recorded.
* Structured ``PolicyViolationFromServer`` errors render via the
  shared ``error_messages.render`` map.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog
from bss_clients import PolicyViolationFromServer
from bss_portal_auth import IdentityView, link_to_customer, record_portal_action
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..clients import get_clients
from ..error_messages import is_known, render
from ..offerings import find_plan, flatten_offerings
from ..prompts import KYC_PREBAKED_ATTESTATION_ID, KYC_PREBAKED_SIGNATURE_TEMPLATE
from ..security import requires_verified_email
from ..session import SignupSession
from ..templating import templates

log = structlog.get_logger(__name__)
router = APIRouter()


# ── GET /signup/{plan_id} ────────────────────────────────────────────────


@router.get("/signup/{plan_id}", response_class=HTMLResponse)
async def signup_form(
    request: Request,
    plan_id: str,
    msisdn: str = Query(default=..., pattern=r"^[0-9]{6,15}$"),
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    clients = get_clients()
    raw = await clients.catalog.list_offerings()
    plan = find_plan(flatten_offerings(raw), plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {plan_id}")
    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "plan": plan,
            "msisdn": msisdn,
            "msisdn_display": _format_msisdn(msisdn),
            "kyc_attestation_id": KYC_PREBAKED_ATTESTATION_ID,
            "identity_email": identity.email,
        },
    )


def _format_msisdn(msisdn: str) -> str:
    if len(msisdn) == 8 and msisdn.isdigit():
        return f"+65 {msisdn[:4]} {msisdn[4:]}"
    return msisdn


# ── POST /signup — step 1: create customer + link identity ──────────────


@router.post("/signup")
async def signup_submit(
    request: Request,
    plan: str = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    msisdn: str = Form(...),
    card_pan: str = Form(...),
    identity: IdentityView = Depends(requires_verified_email),
) -> Response:
    """Run step 1 (``crm.create_customer``) and bind the verified
    identity to the new customer atomically.

    Email is read from ``identity.email`` (the verified session); the
    form never carries ``email`` to defeat the (identity, customer)
    binding invariant. Same posture as v0.8.

    On success: stash CUST-id on the in-memory signup session, advance
    ``session.step`` to ``"pending_kyc"``, redirect to the progress
    page. The HTMX timeline on that page fires the next step routes.
    """
    store = request.app.state.session_store
    factory = request.app.state.db_session_factory
    clients = get_clients()

    session = await store.create(
        plan=plan,
        name=name,
        email=identity.email,
        phone=phone,
        msisdn=msisdn,
        card_pan=card_pan,
        identity_id=identity.id,
    )

    # v0.11 — second-line support. If the verified identity is already
    # linked to a customer (typical case: visitor already signed up
    # once and is now adding another line), reuse that customer_id
    # instead of creating a fresh CRM customer. The chain then jumps
    # past create-customer + KYC (already attested on the prior
    # signup) and the COF step is gated on whether they want a new
    # card or to reuse their existing default. v0.4 / v0.8 / v0.10's
    # signup chain blindly called crm.create_customer every time and
    # left an orphan CUST in CRM if link_to_customer rejected the
    # second link — that's the bug a returning visitor reported.
    existing_customer_id = identity.customer_id
    if existing_customer_id:
        session.customer_id = existing_customer_id
        # Skip create-customer (already exists), KYC (already attested
        # — CRM's ``document_hash_unique_per_tenant`` would reject a
        # duplicate anyway), AND COF (the customer's existing default
        # method on file pays for the new line; no need to make them
        # re-enter card details for a second line). Jump straight to
        # placing the order.
        session.step = "pending_order"
        await _record_step(
            factory,
            session,
            customer_id=existing_customer_id,
            action="signup_create_customer",
            route="/signup",
            success=True,
            error_rule="signup.create_customer.reused_linked_identity",
            request=request,
        )
        await store.update(session)
        return RedirectResponse(
            url=f"/signup/{plan}/progress?session={session.session_id}",
            status_code=303,
        )

    try:
        customer = await clients.crm.create_customer(
            name=name,
            email=identity.email,
            phone=phone,
        )
    except PolicyViolationFromServer as exc:
        await _record_step(
            factory,
            session,
            customer_id=None,
            action="signup_create_customer",
            route="/signup",
            success=False,
            error_rule=exc.rule,
            request=request,
        )
        if not is_known(exc.rule):
            log.info("portal.signup.unknown_policy_rule", rule=exc.rule)
        session.step = "failed"
        session.step_error = exc.rule
        await store.update(session)
        return await _render_failed(request, session, exc.rule)

    customer_id = customer.get("id")
    if not isinstance(customer_id, str):
        # Shouldn't happen — CRM contract is to return id on success.
        # Treat as a failed step with an unknown rule so the audit row
        # captures the anomaly.
        await _record_step(
            factory,
            session,
            customer_id=None,
            action="signup_create_customer",
            route="/signup",
            success=False,
            error_rule="signup.create_customer.no_id",
            request=request,
        )
        session.step = "failed"
        session.step_error = "signup.create_customer.no_id"
        await store.update(session)
        return await _render_failed(
            request, session, "signup.create_customer.no_id"
        )

    session.customer_id = customer_id

    # v0.8 — atomically bind the verified identity to the new customer.
    # Linking BEFORE the rest of the chain runs means a mid-flow abandon
    # still leaves the (identity, customer) pair intact, so a returning
    # visitor under the same email reuses their customer record.
    if factory is not None:
        try:
            async with factory() as db:
                await link_to_customer(
                    db,
                    identity_id=identity.id,
                    customer_id=customer_id,
                )
                await db.commit()
        except ValueError as exc:
            # Identity was already linked to a different customer. The
            # customer record now exists in CRM but the identity points
            # somewhere else; surface as a failed step. No portal-side
            # rollback for the orphan customer — see the v0.10 doctrine
            # carve-out: composition is service-side, not in the route.
            log.warning(
                "portal.signup.link_failed",
                identity_id=identity.id,
                customer_id=customer_id,
                error=str(exc),
            )

    await _record_step(
        factory,
        session,
        customer_id=customer_id,
        action="signup_create_customer",
        route="/signup",
        success=True,
        request=request,
    )

    session.step = "pending_kyc"
    await store.update(session)

    return RedirectResponse(
        url=f"/signup/{plan}/progress?session={session.session_id}",
        status_code=303,
    )


# ── GET /signup/{plan_id}/progress — the deterministic 5-step timeline ──


@router.get("/signup/{plan_id}/progress", response_class=HTMLResponse)
async def signup_progress(
    request: Request,
    plan_id: str,
    session: str,
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    store = request.app.state.session_store
    sig = await store.get(session)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    # Defence-in-depth: a logged-in user shouldn't be able to peek at
    # someone else's in-flight signup by guessing the session id.
    if sig.identity_id and sig.identity_id != identity.id:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")

    return templates.TemplateResponse(
        request,
        "progress.html",
        {
            "session_id": session,
            "plan_id": plan_id,
            "signup": sig,
        },
    )


# ── POST /signup/step/kyc — step 2 ──────────────────────────────────────


@router.post("/signup/step/kyc", response_class=HTMLResponse)
async def signup_step_kyc(
    request: Request,
    session: str = Query(...),
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    store = request.app.state.session_store
    factory = request.app.state.db_session_factory
    sig = await _resolve(store, session, identity)
    if sig.step != "pending_kyc":
        return _render_step_fragment(request, sig)

    clients = get_clients()
    signature = KYC_PREBAKED_SIGNATURE_TEMPLATE.format(email=sig.email)
    try:
        await clients.crm.attest_kyc(
            sig.customer_id,
            provider="myinfo",
            attestation_token=signature,
            provider_reference=KYC_PREBAKED_ATTESTATION_ID,
        )
    except PolicyViolationFromServer as exc:
        await _record_step(
            factory,
            sig,
            customer_id=sig.customer_id,
            action="signup_attest_kyc",
            route="/signup/step/kyc",
            success=False,
            error_rule=exc.rule,
            request=request,
        )
        if not is_known(exc.rule):
            log.info("portal.signup.unknown_policy_rule", rule=exc.rule)
        sig.step = "failed"
        sig.step_error = exc.rule
        await store.update(sig)
        return _render_step_fragment(request, sig)

    await _record_step(
        factory,
        sig,
        customer_id=sig.customer_id,
        action="signup_attest_kyc",
        route="/signup/step/kyc",
        success=True,
        request=request,
    )
    sig.step = "pending_cof"
    await store.update(sig)
    return _render_step_fragment(request, sig)


# ── POST /signup/step/cof — step 3 ──────────────────────────────────────


@router.post("/signup/step/cof", response_class=HTMLResponse)
async def signup_step_cof(
    request: Request,
    session: str = Query(...),
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    store = request.app.state.session_store
    factory = request.app.state.db_session_factory
    sig = await _resolve(store, session, identity)
    if sig.step != "pending_cof":
        return _render_step_fragment(request, sig)

    clients = get_clients()
    try:
        tok = _local_tokenize(sig.card_pan)
    except ValueError:
        await _record_step(
            factory,
            sig,
            customer_id=sig.customer_id,
            action="signup_add_card",
            route="/signup/step/cof",
            success=False,
            error_rule="policy.payment.method.invalid_card",
            request=request,
        )
        sig.step = "failed"
        sig.step_error = "policy.payment.method.invalid_card"
        await store.update(sig)
        return _render_step_fragment(request, sig)

    try:
        method = await clients.payment.create_payment_method(
            customer_id=sig.customer_id,
            card_token=tok["cardToken"],
            last4=tok["last4"],
            brand=tok["brand"],
        )
    except PolicyViolationFromServer as exc:
        await _record_step(
            factory,
            sig,
            customer_id=sig.customer_id,
            action="signup_add_card",
            route="/signup/step/cof",
            success=False,
            error_rule=exc.rule,
            request=request,
        )
        if not is_known(exc.rule):
            log.info("portal.signup.unknown_policy_rule", rule=exc.rule)
        sig.step = "failed"
        sig.step_error = exc.rule
        await store.update(sig)
        return _render_step_fragment(request, sig)

    sig.payment_method_id = method.get("id") if isinstance(method, dict) else None
    # Card PAN cleared from memory the moment the tokenizer + add_card
    # succeed — same posture as v0.4. From here on the only artifact is
    # last-4, which the templates already use.
    sig.card_pan = ""
    await _record_step(
        factory,
        sig,
        customer_id=sig.customer_id,
        action="signup_add_card",
        route="/signup/step/cof",
        success=True,
        request=request,
    )
    sig.step = "pending_order"
    await store.update(sig)
    return _render_step_fragment(request, sig)


# ── POST /signup/step/order — step 4 ────────────────────────────────────


@router.post("/signup/step/order", response_class=HTMLResponse)
async def signup_step_order(
    request: Request,
    session: str = Query(...),
    identity: IdentityView = Depends(requires_verified_email),
) -> HTMLResponse:
    store = request.app.state.session_store
    factory = request.app.state.db_session_factory
    sig = await _resolve(store, session, identity)
    if sig.step != "pending_order":
        return _render_step_fragment(request, sig)

    clients = get_clients()
    try:
        # The orchestrator's ``order.create`` tool wraps create_order +
        # submit_order. The service-side workflow is one conceptual
        # write; we mirror the same composition here so the activation
        # state machine kicks off without a separate user-visible step.
        created = await clients.com.create_order(
            customer_id=sig.customer_id,
            offering_id=sig.plan,
            msisdn_preference=sig.msisdn,
        )
        order_id = created.get("id") if isinstance(created, dict) else None
        if not isinstance(order_id, str):
            raise PolicyViolationFromServer(
                rule="signup.create_order.no_id",
                message="Order create did not return an id.",
            )
        await clients.com.submit_order(order_id)
    except PolicyViolationFromServer as exc:
        await _record_step(
            factory,
            sig,
            customer_id=sig.customer_id,
            action="signup_create_order",
            route="/signup/step/order",
            success=False,
            error_rule=exc.rule,
            request=request,
        )
        if not is_known(exc.rule):
            log.info("portal.signup.unknown_policy_rule", rule=exc.rule)
        sig.step = "failed"
        sig.step_error = exc.rule
        await store.update(sig)
        return _render_step_fragment(request, sig)

    sig.order_id = order_id
    await _record_step(
        factory,
        sig,
        customer_id=sig.customer_id,
        action="signup_create_order",
        route="/signup/step/order",
        success=True,
        request=request,
    )
    sig.step = "pending_activation"
    await store.update(sig)
    return _render_step_fragment(request, sig)


# ── GET /signup/step/poll — step 5 (read-only) ──────────────────────────


@router.get("/signup/step/poll", response_class=HTMLResponse)
async def signup_step_poll(
    request: Request,
    session: str = Query(...),
    identity: IdentityView = Depends(requires_verified_email),
) -> Response:
    """Poll ``com.get_order`` until ``state == completed``.

    No write — the order activation runs server-side via the SOM /
    provisioning workflow. When the order resolves we extract the
    subscription id and emit ``HX-Redirect`` so HTMX swaps the whole
    page to ``/confirmation``.
    """
    store = request.app.state.session_store
    sig = await _resolve(store, session, identity)

    # If the chain already reached completion on a prior poll visit
    # AND the celebration dwell has elapsed (the delayed re-trigger
    # fired this call), emit HX-Redirect now. The first detection
    # below sets ``redirect_armed`` and returns the celebration
    # fragment with a 1.5s delayed re-trigger; the second call lands
    # here and navigates.
    if sig.step == "completed" and sig.redirect_armed and sig.subscription_id:
        resp = HTMLResponse(content="")
        resp.headers["HX-Redirect"] = (
            f"/confirmation/{sig.subscription_id}?session={sig.session_id}"
        )
        return resp

    if sig.step in ("completed", "failed"):
        return _render_step_fragment(request, sig)

    if sig.step != "pending_activation" or not sig.order_id:
        # Still earlier in the chain — render the timeline; the next
        # step's ``hx-trigger="load"`` will fire from the fragment.
        return _render_step_fragment(request, sig)

    clients = get_clients()
    try:
        order = await clients.com.get_order(sig.order_id)
    except Exception:  # noqa: BLE001 — best-effort poll, retry next tick
        return _render_step_fragment(request, sig)

    state = order.get("state") if isinstance(order, dict) else None
    if state == "completed":
        sub_id = _extract_subscription_id(order)
        if not sub_id:
            # Order is "completed" on the COM side but the
            # ``targetSubscriptionId`` hasn't been stamped onto the
            # order item yet — the SOM service emits the activation
            # event before the COM event handler updates the order
            # row, so there's a small race window. Treat as still in
            # progress and re-trigger the poll on the next tick. The
            # next call will see the stamped id.
            return _render_step_fragment(request, sig)
        sig.subscription_id = sub_id
        sig.activation_code = _extract_activation_code(order)
        sig.step = "completed"
        sig.done = True
        sig.redirect_armed = True
        await store.update(sig)
        # First detection — render the "all 5 ticks ✓" celebration
        # fragment. The partial's completed-branch carries a 1.5s
        # delayed re-trigger to /signup/step/poll; that next visit
        # falls through the early ``redirect_armed`` branch above and
        # emits HX-Redirect to /confirmation. The dwell time is
        # deliberate so the user sees the chain finish.
        return _render_step_fragment(request, sig)

    if state in ("failed", "cancelled"):
        sig.step = "failed"
        sig.step_error = f"order.{state}"
        await store.update(sig)
        return _render_step_fragment(request, sig)

    # Still in progress — re-render the fragment, which carries the
    # ``hx-trigger`` to fire again after a short delay.
    return _render_step_fragment(request, sig)


# ── Helpers ─────────────────────────────────────────────────────────────


async def _resolve(
    store: Any,
    session_id: str,
    identity: IdentityView,
) -> SignupSession:
    sig = await store.get(session_id)
    if sig is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    if sig.identity_id and sig.identity_id != identity.id:
        raise HTTPException(status_code=404, detail="Unknown or expired session.")
    return sig


async def _record_step(
    factory: Any,
    sig: SignupSession,
    *,
    customer_id: str | None,
    action: str,
    route: str,
    success: bool,
    error_rule: str | None = None,
    request: Request,
) -> None:
    """Append one ``portal_action`` row per step (success or failure).

    ``factory`` may be ``None`` in unit-test app construction without
    a DB; the failure branch logs and continues so the in-memory
    chain still completes. The structured-error rendering doesn't
    depend on the audit row.
    """
    if factory is None:
        return
    iid = sig.identity_id
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    try:
        async with factory() as db:
            await record_portal_action(
                db,
                customer_id=customer_id,
                identity_id=iid,
                action=action,
                route=route,
                method="POST",
                success=success,
                error_rule=error_rule,
                step_up_consumed=False,
                ip=ip,
                user_agent=ua,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — audit best-effort
        log.warning(
            "portal.signup.audit_failed",
            action=action,
            error=str(exc),
        )


def _render_step_fragment(request: Request, sig: SignupSession) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/signup_progress.html",
        {
            "signup": sig,
            "session_id": sig.session_id,
            "plan_id": sig.plan,
            "step_error_message": (
                render(sig.step_error) if sig.step_error else None
            ),
        },
    )


async def _render_failed(
    request: Request, sig: SignupSession, rule: str
) -> HTMLResponse:
    """POST /signup failure path — re-render the form with a structured error."""
    plan: dict[str, Any] | None = None
    try:
        raw = await get_clients().catalog.list_offerings()
        plan = find_plan(flatten_offerings(raw), sig.plan)
    except Exception:  # noqa: BLE001
        plan = None
    return templates.TemplateResponse(
        request,
        "signup.html",
        {
            "plan": plan or {"id": sig.plan, "name": sig.plan},
            "msisdn": sig.msisdn,
            "msisdn_display": _format_msisdn(sig.msisdn),
            "kyc_attestation_id": KYC_PREBAKED_ATTESTATION_ID,
            "identity_email": sig.email,
            "error": render(rule),
        },
        status_code=422,
    )


def _local_tokenize(card_number: str) -> dict[str, str]:
    """Sandbox client-side tokenizer.

    Mirrors ``routes/payment_methods.py::_local_tokenize`` and the
    orchestrator's ``payment._local_tokenize`` so the v1.0 cutover to
    real Stripe.js / Adyen tokenization doesn't change the wire shape
    from portal → payment service. Embeds ``FAIL`` / ``DECLINE`` in
    the token so the payment service mock can simulate declines.
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


_SUB_ID_KEYS = (
    "targetSubscriptionId",  # COM's TMF622 order-item envelope (real shape)
    "target_subscription_id",
    "subscriptionId",
    "subscription_id",
)


def _extract_subscription_id(order: dict[str, Any]) -> str | None:
    """Pull the SUB-* id off a completed order payload.

    COM's TMF622 order envelope carries the resulting subscription id
    in ``items[*].targetSubscriptionId`` once SOM activation completes
    (verified against ``GET /tmf-api/productOrderingManagement/v4/productOrder/{id}``).
    Scan every item; the first SUB-* wins. Falls back to a few legacy
    aliases (subscriptionId / subscription_id, top-level keys) so
    older envelope shapes and the unit-test fakes both resolve.
    Returns ``None`` if the field isn't there yet — the poll route
    treats that as "still in progress" and retriggers.
    """
    if not isinstance(order, dict):
        return None
    for key in _SUB_ID_KEYS:
        v = order.get(key)
        if isinstance(v, str) and v.startswith("SUB-"):
            return v
    items = order.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in _SUB_ID_KEYS:
                v = item.get(key)
                if isinstance(v, str) and v.startswith("SUB-"):
                    return v
    return None


def _extract_activation_code(order: dict[str, Any]) -> str | None:
    """Optional best-effort lift of the LPA activation code off the order."""
    if not isinstance(order, dict):
        return None
    for key in ("activationCode", "activation_code", "lpa"):
        v = order.get(key)
        if isinstance(v, str):
            return v
    items = order.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("activationCode", "activation_code", "lpa"):
                v = item.get(key)
                if isinstance(v, str):
                    return v
    return None
