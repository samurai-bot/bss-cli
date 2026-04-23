"""Flatten the TMF productOffering payload into plain dicts for templates.

The catalog returns TMF-shaped JSON (``productOfferingPrice[0].price.
taxIncludedAmount.value``, etc.). Templates want simple keys — ``price``,
``data``, ``voice``, ``sms``. This module is the translation seam; it
mirrors the logic in ``cli/bss_cli/renderers/catalog.py`` but emits
dicts instead of ASCII.
"""

from __future__ import annotations

from typing import Any

_PLAN_ORDER = {"PLAN_S": 0, "PLAN_M": 1, "PLAN_L": 2}


def _allowance_str(allowances: list[dict[str, Any]], kind: str) -> str:
    for a in allowances or []:
        atype = a.get("allowanceType") or a.get("type")
        if atype != kind:
            continue
        qty = a.get("quantity") if "quantity" in a else a.get("total")
        unit = a.get("unit", "")
        if qty in (None, "unlimited") or qty == -1:
            return "unlimited"
        if unit == "mb" and isinstance(qty, (int, float)) and qty >= 1024:
            return f"{qty / 1024:g} GB"
        return f"{qty} {unit}".strip()
    return "—"


def _price_str(p: dict[str, Any]) -> str:
    pops = p.get("productOfferingPrice") or []
    if pops:
        amount = (pops[0].get("price") or {}).get("taxIncludedAmount") or {}
        value = amount.get("value")
        if value is not None:
            return f"{value:g}"
    flat = p.get("price") or p.get("monthlyPrice")
    return str(flat) if flat is not None else "?"


def flatten_offerings(offerings: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return template-shaped dicts for PLAN_S / PLAN_M / PLAN_L only.

    Other offerings (VAS top-ups, etc.) are not rendered on the landing
    page — the v0.4 portal is three-plan-bundle signup only.
    """
    plans: list[dict[str, str]] = []
    for p in sorted(
        (o for o in offerings if o.get("id") in _PLAN_ORDER),
        key=lambda o: _PLAN_ORDER[o["id"]],
    ):
        allowances = p.get("bundleAllowance") or p.get("allowances") or []
        voice = _allowance_str(allowances, "voice")
        if voice == "—":
            voice = _allowance_str(allowances, "voice_minutes")
        plans.append(
            {
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "price": _price_str(p),
                "data": _allowance_str(allowances, "data"),
                "voice": voice,
                "sms": _allowance_str(allowances, "sms"),
            }
        )
    return plans


def find_plan(flattened: list[dict[str, str]], plan_id: str) -> dict[str, str] | None:
    for p in flattened:
        if p["id"] == plan_id:
            return p
    return None
