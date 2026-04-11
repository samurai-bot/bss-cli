"""Case policies."""

from app.domain import case_state
from app.policies.base import PolicyViolation, policy
from app.repositories.customer_repo import CustomerRepository
from app.repositories.ticket_repo import TicketRepository


@policy("case.open.customer_must_be_active")
async def check_customer_active(
    customer_id: str, repo: CustomerRepository
) -> None:
    cust = await repo.get(customer_id)
    if not cust:
        raise PolicyViolation(
            rule="case.open.customer_must_be_active",
            message=f"Customer {customer_id} does not exist",
            context={"customer_id": customer_id},
        )
    if cust.status != "active":
        raise PolicyViolation(
            rule="case.open.customer_must_be_active",
            message=f"Customer {customer_id} is not active (status={cust.status})",
            context={"customer_id": customer_id, "status": cust.status},
        )


@policy("case.transition.valid_from_state")
def check_case_transition(current_state: str, trigger: str) -> None:
    if not case_state.is_valid_transition(current_state, trigger):
        raise PolicyViolation(
            rule="case.transition.valid_from_state",
            message=f"Cannot '{trigger}' case from state '{current_state}'",
            context={"current_state": current_state, "trigger": trigger},
        )


@policy("case.close.requires_all_tickets_resolved")
async def check_all_tickets_resolved(
    case_id: str, ticket_repo: TicketRepository
) -> None:
    open_tickets = await ticket_repo.find_open_by_case(case_id)
    if open_tickets:
        ids = [t.id for t in open_tickets]
        raise PolicyViolation(
            rule="case.close.requires_all_tickets_resolved",
            message=f"Case {case_id} has {len(ids)} open tickets: {', '.join(ids)}",
            context={"case_id": case_id, "open_tickets": ids},
        )


@policy("case.close.requires_resolution_code")
def check_resolution_code(resolution_code: str | None) -> None:
    if not resolution_code:
        raise PolicyViolation(
            rule="case.close.requires_resolution_code",
            message="Resolution code is required to close a case",
            context={},
        )
