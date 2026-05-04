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


def _vas_allowance_str(v: dict[str, Any]) -> str:
    """Stringify a VAS allowance for the table row."""
    qty = v.get("allowanceQuantity")
    unit = v.get("allowanceUnit", "")
    if qty in (None, "unlimited") or qty == -1:
        return f"unlimited {unit}".strip()
    if unit == "mb" and isinstance(qty, (int, float)) and qty >= 1024:
        return f"{qty / 1024:g} GB"
    return f"{qty} {unit}".strip()


def render_vas_list(vas: list[dict[str, Any]]) -> str:
    """v0.19 — render the catalog.list_vas response as an ASCII table.

    Wired into the REPL post-processor so the agent can't fabricate
    VAS prices/names from prompt context (was happening pre-v0.19
    because the dispatcher only had catalog.list_offerings).
    """
    if not vas:
        return "(no VAS offerings in catalog)"

    rows = []
    for v in vas:
        vid = v.get("id", "?")
        name = v.get("name", "")
        ccy = v.get("currency", "SGD")
        amount = v.get("priceAmount", "?")
        allowance = _vas_allowance_str(v)
        expiry = v.get("expiryHours")
        expiry_s = f"{expiry}h" if expiry else "—"
        rows.append((vid, name, f"{ccy} {amount}", allowance, expiry_s))

    col1 = max(len("id"), max(len(r[0]) for r in rows))
    col2 = max(len("name"), max(len(r[1]) for r in rows))
    col3 = max(len("price"), max(len(r[2]) for r in rows))
    col4 = max(len("allowance"), max(len(r[3]) for r in rows))
    col5 = max(len("expiry"), max(len(r[4]) for r in rows))

    inner = col1 + col2 + col3 + col4 + col5 + 4 * 3 + 2

    def _row(c1, c2, c3, c4, c5):
        return (
            f"│ {c1.ljust(col1)} │ {c2.ljust(col2)} │ "
            f"{c3.ljust(col3)} │ {c4.ljust(col4)} │ {c5.ljust(col5)} │"
        )

    title = " VAS Offerings "
    out = ["┌─" + title + "─" * max(2, inner - len(title) - 2) + "┐"]
    out.append(_row("id", "name", "price", "allowance", "expiry"))
    out.append(_row("─" * col1, "─" * col2, "─" * col3, "─" * col4, "─" * col5))
    for r in rows:
        out.append(_row(*r))
    out.append("└" + "─" * (inner) + "┘")
    return "\n".join(out)


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
