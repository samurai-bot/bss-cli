"""Customer policies."""

from app.policies.base import PolicyViolation, policy
from app.repositories.customer_repo import CustomerRepository


@policy("customer.create.email_unique")
async def check_email_unique(email: str, repo: CustomerRepository) -> None:
    existing = await repo.find_by_email(email)
    if existing:
        raise PolicyViolation(
            rule="customer.create.email_unique",
            message=f"Email '{email}' is already registered",
            context={"email": email},
        )


@policy("customer.create.requires_contact_medium")
def check_requires_contact_medium(contact_mediums: list[dict]) -> None:
    if not contact_mediums:
        raise PolicyViolation(
            rule="customer.create.requires_contact_medium",
            message="At least one contact medium (email or phone) is required",
            context={},
        )


@policy("customer.close.no_active_subscriptions")
async def check_no_active_subscriptions(customer_id: str) -> None:
    # Stub — real check wired in Phase 6 via bss-clients HTTP call
    # to subscription service: GET /subscription-api/v1/subscription?customerId=...&state=active
    pass
