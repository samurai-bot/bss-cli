# ============================================================================
#  SANDBOX ONLY — NEVER STORE PAN OR CVV IN A REAL SYSTEM
#
#  In production, card numbers go directly from the client (mobile app, web
#  portal) to a PCI-compliant tokenization service (Stripe, Adyen, Checkout.com,
#  etc). The backend ONLY ever sees the resulting token.
#
#  This mock tokenizes server-side PURELY for demo simplicity and MUST NOT
#  be used as a production pattern. The public POST /paymentMethod endpoint
#  takes a pre-tokenized request — this module is only invoked from tests
#  and from `bss payment add-card` in dev mode (gated behind
#  BSS_ENABLE_DEV_TOKENIZER).
# ============================================================================

"""Mock card tokenizer — pure functions, no DB, no HTTP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from bss_clock import now as clock_now


@dataclass(frozen=True)
class TokenizeResult:
    token: str
    last4: str
    brand: str


@dataclass(frozen=True)
class ChargeResult:
    status: str       # "approved" or "declined"
    gateway_ref: str  # "mock_<uuid4>"
    reason: str | None  # None if approved


def _detect_brand(card_number: str) -> str:
    """BIN-based brand detection."""
    digits = card_number.replace(" ", "").replace("-", "")
    if not digits:
        return "unknown"
    if digits[0] == "4":
        return "visa"
    if len(digits) >= 2 and digits[:2] in ("34", "37"):
        return "amex"
    if len(digits) >= 2 and 51 <= int(digits[:2]) <= 55:
        return "mastercard"
    return "unknown"


def tokenize_card(
    card_number: str, exp_month: int, exp_year: int, cvv: str
) -> TokenizeResult:
    """Tokenize a card number into a mock token.

    Pure function — no DB, no HTTP.
    - BIN-based brand detection (4xxx=visa, 51-55=mc, 34/37=amex)
    - card_number containing "FAIL" or "DECLINE" embeds that in the token
    - Expired card raises ValueError
    """
    now = clock_now()
    if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
        raise ValueError(
            f"Card expired: {exp_month:02d}/{exp_year}"
        )

    digits = card_number.replace(" ", "").replace("-", "")
    last4 = digits[-4:] if len(digits) >= 4 else digits
    brand = _detect_brand(digits)

    # Special-case: embed FAIL/DECLINE in the token so charge() knows to decline
    uid = str(uuid4())
    if "FAIL" in card_number.upper():
        token = f"tok_FAIL_{uid}"
    elif "DECLINE" in card_number.upper():
        token = f"tok_DECLINE_{uid}"
    else:
        token = f"tok_{uid}"

    return TokenizeResult(token=token, last4=last4, brand=brand)


async def charge(token: str, amount: Decimal, currency: str) -> ChargeResult:
    """Simulate a gateway charge.

    Pure function with simulated latency — no DB, no HTTP.
    - token containing "FAIL" or "DECLINE" → declined
    - amount <= 0 → ValueError
    - else → approved with mock gateway ref
    """
    await asyncio.sleep(0.05)  # simulate gateway latency

    if amount <= 0:
        raise ValueError("amount must be positive")

    gateway_ref = f"mock_{uuid4()}"

    if "FAIL" in token or "DECLINE" in token:
        return ChargeResult(
            status="declined",
            reason="card_declined_by_issuer",
            gateway_ref=gateway_ref,
        )

    return ChargeResult(
        status="approved",
        reason=None,
        gateway_ref=gateway_ref,
    )
