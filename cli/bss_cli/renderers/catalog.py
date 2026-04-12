"""Catalog renderer — three-column plan comparison."""

from __future__ import annotations

from typing import Any


def _allowance_str(allowances: list[dict[str, Any]], kind: str) -> str:
    # TMF payload uses ``allowanceType`` + ``quantity``; our simplified shape
    # uses ``type`` + ``total``. Accept either.
    for a in allowances or []:
        atype = a.get("allowanceType") or a.get("type")
        if atype == kind:
            qty = a.get("quantity") if "quantity" in a else a.get("total")
            unit = a.get("unit", "")
            # Catalog uses ``-1`` as an unlimited sentinel; treat it as such.
            if qty in (None, "unlimited") or qty == -1:
                return "unlimited"
            # Prettify MB → GB for readability when ≥ 1024 MB.
            if unit == "mb" and isinstance(qty, (int, float)) and qty >= 1024:
                return f"{qty / 1024:g} GB"
            return f"{qty} {unit}".strip()
    return "—"


def _price_str(p: dict[str, Any]) -> str:
    # TMF: productOfferingPrice[0].price.taxIncludedAmount.value
    pops = p.get("productOfferingPrice") or []
    if pops:
        amount = (pops[0].get("price") or {}).get("taxIncludedAmount") or {}
        value = amount.get("value")
        if value is not None:
            return f"{value:g}"
    # Fallback to flat shape used in tests.
    flat = p.get("price") or p.get("monthlyPrice")
    return str(flat) if flat is not None else "?"


def render_catalog(offerings: list[dict[str, Any]]) -> str:
    """Render a 3-column plan comparison for PLAN_S/PLAN_M/PLAN_L."""
    order = {"PLAN_S": 0, "PLAN_M": 1, "PLAN_L": 2}
    plans = sorted(
        [o for o in offerings if o.get("id") in order],
        key=lambda o: order[o["id"]],
    )
    if not plans:
        return "(no plans in catalog)"

    cols = []
    for p in plans:
        name = p.get("name", p.get("id", "?"))
        price = _price_str(p)
        allowances = p.get("bundleAllowance") or p.get("allowances") or []
        data = _allowance_str(allowances, "data")
        voice = _allowance_str(allowances, "voice")
        if voice == "—":
            voice = _allowance_str(allowances, "voice_minutes")
        sms = _allowance_str(allowances, "sms")

        col = [
            f"── {p['id']}  {name} ──",
            f"  SGD {price} /mo",
            "",
            f"  Data    {data}",
            f"  Voice   {voice}",
            f"  SMS     {sms}",
        ]
        cols.append(col)

    # Assemble side-by-side
    width = max(len(line) for col in cols for line in col) + 2
    max_rows = max(len(col) for col in cols)
    out_lines = ["┌─ Product Offerings " + "─" * 50 + "┐"]
    for i in range(max_rows):
        parts = []
        for col in cols:
            parts.append(col[i].ljust(width) if i < len(col) else " " * width)
        out_lines.append("│  " + "  ".join(parts).rstrip().ljust(72 - 3) + " │")
    out_lines.append("└" + "─" * 70 + "┘")
    return "\n".join(out_lines)
