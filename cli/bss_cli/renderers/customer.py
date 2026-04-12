"""Customer 360 renderer — status, contact, subscriptions, cases, interactions."""

from __future__ import annotations

from typing import Any

from ._box import box, format_msisdn, state_dot


def _contact_line(contact_mediums: list[dict[str, Any]]) -> str:
    email = None
    phone = None
    for cm in contact_mediums or []:
        ch = cm.get("characteristic", {}) or {}
        if cm.get("mediumType") == "email":
            email = ch.get("emailAddress")
        elif cm.get("mediumType") == "mobile":
            phone = ch.get("phoneNumber")
    parts = [p for p in (email, phone) if p]
    return " · ".join(parts) if parts else "—"


def render_customer_360(
    customer: dict[str, Any],
    *,
    subscriptions: list[dict[str, Any]] | None = None,
    cases: list[dict[str, Any]] | None = None,
    tickets_by_case: dict[str, list[dict[str, Any]]] | None = None,
    interactions: list[dict[str, Any]] | None = None,
) -> str:
    """Render the customer 360 hero view."""
    cid = customer.get("id", "CUST-???")
    name = customer.get("name", "—")
    status = customer.get("status", "unknown")
    since = customer.get("createdAt") or customer.get("since", "—")
    contact = _contact_line(customer.get("contactMedium") or [])

    subscriptions = subscriptions or []
    cases = cases or []
    tickets_by_case = tickets_by_case or {}
    interactions = interactions or []

    lines: list[str] = []
    lines.append(f"Status: {state_dot(status)}   since {since}")
    lines.append(f"Contact: {contact}")
    lines.append("")

    lines.append(f"── Subscriptions ({len(subscriptions)}) " + "─" * 30)
    if not subscriptions:
        lines.append("(none)")
    for s in subscriptions:
        pct = ""
        balances = s.get("balances") or []
        for b in balances:
            if b.get("type") == "data" and b.get("total"):
                used = float(b.get("used", 0))
                total = float(b["total"])
                pct = f" bundle {int((used / total) * 100)}%" if total else ""
                break
        lines.append(
            f"{s.get('id', '?'):<8} {s.get('offeringId', '?'):<8} "
            f"{s.get('state', '?'):<8}  MSISDN {format_msisdn(s.get('msisdn', ''))}{pct}"
        )
    lines.append("")

    open_cases = [c for c in cases if c.get("state") not in ("closed", "resolved")]
    lines.append(f"── Open Cases ({len(open_cases)}) " + "─" * 32)
    if not open_cases:
        lines.append("(none)")
    for c in open_cases:
        lines.append(
            f"{c.get('id'):<9}  {c.get('subject', '')!r:<30} "
            f"{c.get('priority', ''):<7} {c.get('state', '')}"
        )
        for t in tickets_by_case.get(c.get("id"), []):
            lines.append(
                f"  └─ {t.get('id'):<8} {t.get('ticketType', ''):<18} "
                f"{t.get('priority', ''):<7} {t.get('state', '')}"
            )
    lines.append("")

    lines.append(f"── Recent Interactions ({len(interactions)}) " + "─" * 22)
    for it in interactions[:5]:
        lines.append(
            f"{it.get('createdAt', '')[:16]}  {it.get('channel', ''):<8} "
            f"{it.get('action', '')}"
        )
    if not interactions:
        lines.append("(none)")

    return box(lines, title=f"{cid}  {name}", width=64)
