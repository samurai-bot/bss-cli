"""Catalog renderer — three-column plan comparison + single-plan card."""

from __future__ import annotations

from typing import Any

# PLAN_M is the recommended default — gets a ★ marker on the comparison
# table so the operator's eye lands on it first. Spec carry-over from
# v0.6 renderer polish.
_POPULAR_PLAN = "PLAN_M"

_PLAN_ORDER = {"PLAN_S": 0, "PLAN_M": 1, "PLAN_L": 2}


def _allowance_str(allowances: list[dict[str, Any]], kind: str) -> str:
    """Stringify a single allowance row (data/voice/sms) as human units."""
    for a in allowances or []:
        atype = a.get("allowanceType") or a.get("type")
        if atype != kind:
            continue
        qty = a.get("quantity") if "quantity" in a else a.get("total")
        unit = a.get("unit", "")
        if qty in (None, "unlimited") or qty == -1:
            return "unlimited"
        # Prettify MB → GB once we hit the GB threshold.
        if unit == "mb" and isinstance(qty, (int, float)) and qty >= 1024:
            gb = qty / 1024
            return f"{gb:g} GB"
        if unit in ("min", "minutes"):
            return f"{qty} min"
        if unit in ("sms", "count"):
            return f"{qty} sms"
        return f"{qty} {unit}".strip()
    return "—"


def _price_str(p: dict[str, Any]) -> str:
    """SGD price string (no currency prefix)."""
    pops = p.get("productOfferingPrice") or []
    if pops:
        amount = (pops[0].get("price") or {}).get("taxIncludedAmount") or {}
        value = amount.get("value")
        if value is not None:
            return f"{value:g}"
    flat = p.get("price") or p.get("monthlyPrice")
    return str(flat) if flat is not None else "?"


def _ordered_plans(offerings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [o for o in offerings if o.get("id") in _PLAN_ORDER],
        key=lambda o: _PLAN_ORDER[o["id"]],
    )


def render_catalog(offerings: list[dict[str, Any]]) -> str:
    """Three-column plan comparison: PLAN_S / PLAN_M / PLAN_L side-by-side."""
    plans = _ordered_plans(offerings)
    if not plans:
        return "(no plans in catalog)"

    cols: list[list[str]] = []
    for p in plans:
        name = p.get("name", p.get("id", "?"))
        price = _price_str(p)
        allowances = p.get("bundleAllowance") or p.get("allowances") or []
        data = _allowance_str(allowances, "data")
        voice = _allowance_str(allowances, "voice")
        if voice == "—":
            voice = _allowance_str(allowances, "voice_minutes")
        sms = _allowance_str(allowances, "sms")

        # Header gets a ★ on the popular plan so the eye lands on it first.
        marker = " ★" if p["id"] == _POPULAR_PLAN else ""
        header = f"{p['id']}{marker}  {name}"
        # v0.17 — show roaming when the plan carries any (PLAN_S has 0
        # and renders "—"; PLAN_M/L show their bundled MB).
        roaming = _allowance_str(allowances, "data_roaming")
        col = [
            header,
            f"SGD {price} /mo",
            "",
            f"Data    {data}",
            f"Voice   {voice}",
            f"SMS     {sms}",
            f"Roaming {roaming}",
        ]
        cols.append(col)

    col_width = 22  # fixed col width keeps the 3-col grid aligned
    sep = "  "
    inner_content = col_width * 3 + len(sep) * 2  # 66 chars of payload
    inner = inner_content + 4  # +4 for "  " left pad + " │" right pad spacing
    title = "Product Offerings"
    out_lines = ["┌─ " + title + " " + "─" * max(2, inner - len(title) - 4) + "┐"]
    for i in range(max(len(col) for col in cols)):
        parts = [col[i] if i < len(col) else "" for col in cols]
        row = sep.join(part.ljust(col_width) for part in parts)
        out_lines.append("│  " + row.ljust(inner - 4) + "  │")
    out_lines.append("│  " + ("Prices in SGD, GST inclusive.").ljust(inner - 4) + "  │")
    out_lines.append("└" + "─" * inner + "┘")
    return "\n".join(out_lines)


def render_catalog_show(offering: dict[str, Any]) -> str:
    """Expanded card for a single plan — `bss catalog show PLAN_M`."""
    pid = offering.get("id", "?")
    name = offering.get("name", pid)
    price = _price_str(offering)
    allowances = offering.get("bundleAllowance") or offering.get("allowances") or []
    data = _allowance_str(allowances, "data")
    voice = _allowance_str(allowances, "voice")
    if voice == "—":
        voice = _allowance_str(allowances, "voice_minutes")
    sms = _allowance_str(allowances, "sms")
    # v0.17 — additive roaming bucket. Shown only when the plan has
    # quota; PLAN_S has 0 mb so the row is suppressed (consistent with
    # the portal line_card filter).
    roaming = _allowance_str(allowances, "data_roaming")

    marker = "  ★ MOST POPULAR" if pid == _POPULAR_PLAN else ""
    title = f"{pid}  {name}{marker}"
    width = 60
    top = "┌─ " + title + " " + "─" * max(0, width - len(title) - 4) + "┐"
    bottom = "└" + "─" * (width - 1) + "┘"

    rows = [
        top,
        f"│ Price       SGD {price} / month  (GST inclusive)" + " " * max(0, width - len(f"│ Price       SGD {price} / month  (GST inclusive)") - 1) + "│",
        f"│ " + " " * (width - 3) + "│",
        f"│ Bundle (every 30 days):" + " " * max(0, width - 26) + "│",
        f"│   Data        {data}" + " " * max(0, width - len(f"│   Data        {data}") - 1) + "│",
        f"│   Voice       {voice}" + " " * max(0, width - len(f"│   Voice       {voice}") - 1) + "│",
        f"│   SMS         {sms}" + " " * max(0, width - len(f"│   SMS         {sms}") - 1) + "│",
    ]
    if roaming != "—":
        rows.append(
            f"│   Roaming     {roaming}"
            + " " * max(0, width - len(f"│   Roaming     {roaming}") - 1)
            + "│"
        )
    rows.extend([
        f"│ " + " " * (width - 3) + "│",
        f"│ Block-on-exhaust. Top up via VAS or wait for renewal." + " " * max(0, width - 56) + "│",
        bottom,
    ])
    return "\n".join(rows)
