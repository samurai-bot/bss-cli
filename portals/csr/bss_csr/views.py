"""View-model adapters — flatten bss-clients TMF payloads into the
shape the CSR portal templates render.

Templates stay dumb (read keys, don't compute); the flattening lives
here so the same projection is reusable across the customer 360 page,
the auto-refresh partials, and the test assertions.
"""

from __future__ import annotations

from typing import Any


def flatten_customer(raw: dict[str, Any]) -> dict[str, Any]:
    """TMF629 customer → simple dict for the customer summary card."""
    individual = raw.get("individual") or {}
    name = " ".join(
        s for s in [individual.get("givenName"), individual.get("familyName")] if s
    ).strip() or raw.get("id", "(unnamed)")
    contacts = raw.get("contactMedium") or []
    email = next((c["value"] for c in contacts if c.get("mediumType") == "email"), "")
    phone = next((c["value"] for c in contacts if c.get("mediumType") == "mobile"), "")
    return {
        "id": raw.get("id", ""),
        "name": name,
        "email": email,
        "phone": phone,
        "status": raw.get("status", "unknown"),
        "kyc_status": raw.get("kycStatus", "unknown"),
        "customer_since": raw.get("customerSince", ""),
    }


def flatten_subscription(raw: dict[str, Any]) -> dict[str, Any]:
    """Subscription record → card-shaped dict with balances rolled up."""
    balances_raw = raw.get("balances") or []
    balances = [
        {
            "type": b.get("allowanceType", b.get("type", "")),
            "remaining": b.get("remaining"),
            "total": b.get("total"),
            "unit": b.get("unit", ""),
        }
        for b in balances_raw
    ]
    return {
        "id": raw.get("id", ""),
        "state": raw.get("state", "unknown"),
        "offering_id": raw.get("offeringId", ""),
        "msisdn": raw.get("msisdn", ""),
        "iccid": raw.get("iccid", ""),
        "balances": balances,
        "next_renewal": raw.get("nextRenewalAt", ""),
    }


def flatten_case(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id", ""),
        "subject": raw.get("subject", ""),
        "state": raw.get("state", "unknown"),
        "priority": raw.get("priority", ""),
        "category": raw.get("category", ""),
        "open_tickets": len(
            [t for t in raw.get("tickets", []) if t.get("state") not in ("resolved", "closed")]
        ),
    }


def flatten_payment_method(raw: dict[str, Any]) -> dict[str, Any]:
    summary = raw.get("cardSummary") or {}
    return {
        "id": raw.get("id", ""),
        "brand": summary.get("brand", "card"),
        "last4": summary.get("last4", "????"),
        "exp": f"{summary.get('expMonth', '??'):02d}/{summary.get('expYear', '????')}"
        if summary.get("expMonth")
        else "",
        "is_default": raw.get("isDefault", False),
        "status": raw.get("status", "unknown"),
    }


def flatten_interaction(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id", ""),
        "channel": raw.get("channel", ""),
        "direction": raw.get("direction", ""),
        "summary": raw.get("summary", ""),
        "occurred_at": raw.get("occurredAt", ""),
    }


def looks_like_msisdn(q: str) -> bool:
    """True if ``q`` is plausibly a phone number (digits only, ≥ 6)."""
    digits = q.strip().lstrip("+").replace(" ", "")
    return digits.isdigit() and len(digits) >= 6
