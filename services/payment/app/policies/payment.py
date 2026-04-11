"""Payment charge policies — 3 rules.

payment.charge.method_active
payment.charge.positive_amount
payment.charge.customer_matches_method
"""

from __future__ import annotations

from decimal import Decimal

from bss_models import PaymentMethod

from .base import PolicyViolation, policy


@policy("payment.charge.method_active")
def check_method_active(method: PaymentMethod) -> None:
    """Payment method must be active (not removed)."""
    if method.status != "active":
        raise PolicyViolation(
            rule="payment.charge.method_active",
            message=f"Payment method {method.id} status is '{method.status}', must be active",
            context={"payment_method_id": method.id, "status": method.status},
        )


@policy("payment.charge.positive_amount")
def check_positive_amount(amount: Decimal) -> None:
    """Charge amount must be positive."""
    if amount <= 0:
        raise PolicyViolation(
            rule="payment.charge.positive_amount",
            message=f"Charge amount must be positive, got {amount}",
            context={"amount": str(amount)},
        )


@policy("payment.charge.customer_matches_method")
def check_customer_matches_method(
    customer_id: str, method: PaymentMethod
) -> None:
    """Customer ID on charge request must match the method's customer_id."""
    if method.customer_id != customer_id:
        raise PolicyViolation(
            rule="payment.charge.customer_matches_method",
            message=f"Payment method {method.id} belongs to {method.customer_id}, not {customer_id}",
            context={
                "requested_customer_id": customer_id,
                "method_customer_id": method.customer_id,
                "payment_method_id": method.id,
            },
        )
