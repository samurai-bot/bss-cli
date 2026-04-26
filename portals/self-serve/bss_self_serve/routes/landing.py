"""Login-gated `/` — customer dashboard (v0.10 fills the placeholder).

History:

* v0.4 mounted ``/`` as the anonymous plan-cards landing.
* v0.8 made ``/`` the login-gated dashboard with two states (unlinked
  empty / linked placeholder).
* v0.10 fills in the linked path: list the customer's subscriptions
  with state-aware CTAs, balance bars, days remaining, and a pending
  plan-change banner where applicable.

Doctrine (V0_10_0.md Track 2):

* Reads only — the dashboard does not write. ``customer_id`` is bound
  from ``request.state.customer_id`` (verified session); the call to
  ``subscription.list_for_customer`` is server-side scoped by that id,
  so cross-customer reads are not possible from this route.
* No orchestrator. The reads go directly via the v0.9
  ``NamedTokenAuthProvider`` clients — same pattern v0.8 used for the
  placeholder. ``audit.domain_event`` rows recorded on writes (which
  this route does not perform) carry ``service_identity =
  "portal_self_serve"`` via the named token.
"""

from __future__ import annotations

import asyncio
from typing import Any

from bss_portal_auth import IdentityView, SessionView
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..clients import get_clients
from ..security import requires_session
from ..templating import templates

router = APIRouter()


# Allowance type → label shown on the line card. Lowercase keys
# match the BSS subscription.balance response.
ALLOWANCE_LABEL = {
    "data": "Data",
    "voice": "Voice",
    "sms": "SMS",
}


def _bar_for(balance: dict[str, Any]) -> dict[str, Any]:
    """Compute the proportional fill for a single allowance.

    Mirrors the v0.6 ASCII bar's intent (proportional, not flat
    blocks). Returns a dict the template renders as a CSS-gradient
    width: ``percent`` is a 0..100 integer, ``low`` flips the bar's
    visual treatment under 10%, and ``unlimited`` uses a dashed-fill
    rendering for ``total = -1``.
    """
    total = int(balance.get("total", 0))
    consumed = int(balance.get("consumed", 0))
    remaining = int(balance.get("remaining", max(total - consumed, 0)))

    if total < 0:
        return {
            "label": ALLOWANCE_LABEL.get(balance.get("allowanceType", ""), "?"),
            "unit": balance.get("unit", ""),
            "remaining": remaining,
            "total": total,
            "percent": 100,
            "unlimited": True,
            "low": False,
            "exhausted": False,
        }

    percent = 0
    if total > 0:
        # Proportional fill — same intent as v0.6 progress_bar's
        # sub-cell resolution. We round to the nearest integer
        # percent so the CSS width attribute is small + greppable.
        percent = max(0, min(100, round((remaining / total) * 100)))

    return {
        "label": ALLOWANCE_LABEL.get(balance.get("allowanceType", ""), "?"),
        "unit": balance.get("unit", ""),
        "remaining": remaining,
        "total": total,
        "percent": percent,
        "unlimited": False,
        "low": 0 < percent <= 10,
        "exhausted": remaining <= 0 and total > 0,
    }


def _days_remaining(period_end: str | None, now_iso: str) -> int | None:
    """Days from ``now`` to ``period_end`` (positive int, 0, or None).

    Both inputs are ISO-8601 strings (BSS service responses serialise
    timestamps as ISO via Pydantic). Returns None if ``period_end`` is
    unset (e.g. pending_activation lines have no current period yet).
    """
    if not period_end:
        return None
    from datetime import datetime

    end = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    delta = end - now
    return max(0, delta.days)


def _cta_for(state: str, has_pending_plan_change: bool) -> str:
    """Pick the dashboard CTA branch label.

    Branches map 1:1 to the V0_10_0.md Track 2.1 list. The template
    consumes this string to render the right button block; we keep
    the branch logic in Python so adding a new state is a single
    Python edit + a single template block, not three.
    """
    if state == "active" and has_pending_plan_change:
        return "pending_plan_change"
    if state == "blocked":
        return "blocked"
    if state == "pending_activation":
        return "pending_activation"
    if state == "terminated":
        return "terminated"
    return "active"


async def _line_view(
    sub: dict[str, Any],
    *,
    offering_name: str,
    now_iso: str,
    balances: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the per-line dict the line_card template consumes."""
    state = sub.get("state", "")
    has_pending = sub.get("pendingOfferingId") is not None
    return {
        "id": sub["id"],
        "msisdn": sub.get("msisdn", ""),
        "state": state,
        "state_label": state.replace("_", " ").upper(),
        "offering_id": sub.get("offeringId", ""),
        "offering_name": offering_name,
        "current_period_end": sub.get("currentPeriodEnd"),
        "next_renewal_at": sub.get("nextRenewalAt"),
        "terminated_at": sub.get("terminatedAt"),
        "days_remaining": _days_remaining(sub.get("currentPeriodEnd"), now_iso),
        "pending_offering_id": sub.get("pendingOfferingId"),
        "pending_effective_at": sub.get("pendingEffectiveAt"),
        "cta_branch": _cta_for(state, has_pending),
        "bars": [_bar_for(b) for b in balances],
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _session: SessionView = Depends(requires_session),
) -> HTMLResponse:
    """Login-gated dashboard.

    Branches on the linked-customer state:

    * No session                      → handled by ``requires_session``.
    * Verified email, no customer_id  → empty dashboard with /plans CTA.
    * Verified email + customer_id    → list of line cards.
    """
    identity: IdentityView | None = getattr(request.state, "identity", None)
    if identity is None or identity.customer_id is None:
        return templates.TemplateResponse(
            request,
            "dashboard_empty.html",
            {"email": getattr(identity, "email", None)},
        )

    customer_id = identity.customer_id
    clients = get_clients()

    # Pull subscriptions + the catalogue once. The catalogue lookup is
    # for human-readable plan names; one offering-list call beats N
    # per-subscription lookups for the dashboard's small N.
    subs: list[dict[str, Any]] = await clients.subscription.list_for_customer(
        customer_id
    )

    if not subs:
        return templates.TemplateResponse(
            request,
            "dashboard_empty.html",
            {"email": identity.email},
        )

    offerings: list[dict[str, Any]] = await clients.catalog.list_offerings()
    offering_name_by_id = {o["id"]: o.get("name", o["id"]) for o in offerings}

    # Per-subscription balance reads run in parallel — small N, but
    # the dashboard's sub-second budget is real.
    async def _safe_balance(sub_id: str) -> list[dict[str, Any]]:
        try:
            return await clients.subscription.get_balance(sub_id)
        except Exception:  # pragma: no cover - upstream error path
            # A 404 (no balances yet, e.g. pending_activation) renders
            # an empty bar set rather than failing the whole dashboard.
            return []

    balances_by_sub = await asyncio.gather(
        *(_safe_balance(s["id"]) for s in subs)
    )

    from bss_clock import now as clock_now

    now_iso = clock_now().isoformat()
    lines = [
        await _line_view(
            sub,
            offering_name=offering_name_by_id.get(
                sub.get("offeringId", ""), sub.get("offeringId", "")
            ),
            now_iso=now_iso,
            balances=bals,
        )
        for sub, bals in zip(subs, balances_by_sub)
    ]
    # Resolve pending offering names too, where present, so the
    # "switching to <name> on <date>" badge reads naturally.
    for line in lines:
        pending_id = line.get("pending_offering_id")
        if pending_id:
            line["pending_offering_name"] = offering_name_by_id.get(
                pending_id, pending_id
            )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": identity.email,
            "customer_id": customer_id,
            "lines": lines,
        },
    )
