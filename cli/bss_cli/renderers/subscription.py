"""Subscription hero renderer — the flagship ASCII view."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ._box import box, format_msisdn, progress_bar, state_dot

_UNLIMITED_UNITS = {"unlimited", "unlim"}


def _fmt_balance(used: float, total: float | None, unit: str) -> str:
    if total is None or (isinstance(total, str) and total in _UNLIMITED_UNITS):
        return f"{progress_bar(0, None)}  unlimited"
    pct = 0 if not total else int(round((used / total) * 100))
    return f"{progress_bar(used, total)}  {used:.1f} / {total:.1f} {unit.upper()}  {pct}%"


def _days_to(dt_str: str | None, now: datetime | None = None) -> str:
    if not dt_str:
        return "—"
    try:
        then = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return dt_str
    now = now or datetime.now(then.tzinfo or timezone.utc)
    delta = then - now
    days = delta.days
    return f"{days} days ({then.date().isoformat()})"


def render_subscription(
    sub: dict[str, Any],
    *,
    customer: dict[str, Any] | None = None,
    offering: dict[str, Any] | None = None,
) -> str:
    """Render the subscription hero view (bundle bars + state + countdown)."""
    sub_id = sub.get("id", "SUB-???")
    cust_id = sub.get("customerId", "—")
    cust_name = (customer or {}).get("name", "—")
    msisdn = format_msisdn(sub.get("msisdn", ""))
    plan_name = (offering or {}).get("name", "—")
    plan_id = sub.get("offeringId", "—")
    price = (offering or {}).get("price")
    price_str = f" — SGD {price}/mo" if price else ""
    state = sub.get("state", "unknown")

    activated = sub.get("activatedAt") or sub.get("startDate") or "—"
    next_renewal = sub.get("nextRenewalAt") or sub.get("endDate")

    balances = sub.get("balances") or sub.get("bundleBalances") or []
    # Normalize balance rows
    rows: list[str] = []
    for b in balances:
        label = str(b.get("type", "?")).title()
        used = float(b.get("used", 0))
        total = b.get("total")
        if total in (None, "unlimited"):
            total_val: float | None = None
        else:
            total_val = float(total)
        unit = b.get("unit", "")
        rows.append(f"{label:<7} {_fmt_balance(used, total_val, unit)}")

    if not rows:
        rows = ["(no bundle balances)"]

    lines = [
        "",
        f"Customer:    {cust_name} ({cust_id})",
        f"MSISDN:      {msisdn}",
        f"Plan:        {plan_name} ({plan_id}){price_str}",
        f"State:       {state_dot(state)}",
        f"Activated:   {activated}",
        f"Renews in:   {_days_to(next_renewal)}",
        "",
        "── Bundle " + "─" * 50,
        *rows,
        "",
    ]
    return box(lines, title=f"Subscription {sub_id}", width=64)
