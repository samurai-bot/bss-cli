"""Customer service — orchestrates policies, repos, events."""

from datetime import datetime, timezone
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_context
from app.events import publisher
from app.policies import customer as customer_policies
from app.repositories.customer_repo import CustomerRepository
from app.repositories.interaction_repo import InteractionRepository
from bss_models.crm import ContactMedium, Customer, Individual, Interaction, Party

log = structlog.get_logger()


def _next_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class CustomerService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        customer_repo: CustomerRepository,
        interaction_repo: InteractionRepository,
    ) -> None:
        self._session = session
        self._customer_repo = customer_repo
        self._interaction_repo = interaction_repo

    async def create_customer(
        self,
        *,
        given_name: str,
        family_name: str,
        date_of_birth: str | None = None,
        contact_mediums: list[dict],
    ) -> Customer:
        ctx = auth_context.current()

        # --- Policies ---
        customer_policies.check_requires_contact_medium(contact_mediums)

        emails = [cm["value"] for cm in contact_mediums if cm.get("medium_type") == "email"]
        for email in emails:
            await customer_policies.check_email_unique(email, self._customer_repo)

        # --- Create aggregate ---
        now = datetime.now(timezone.utc)
        party_id = _next_id("PTY")
        customer_id = _next_id("CUST")

        party = Party(id=party_id, party_type="individual", tenant_id=ctx.tenant)
        await self._customer_repo.create_party(party)

        dob = None
        if date_of_birth:
            from datetime import date as date_type
            dob = date_type.fromisoformat(date_of_birth)
        individual = Individual(
            party_id=party_id,
            given_name=given_name,
            family_name=family_name,
            date_of_birth=dob,
            tenant_id=ctx.tenant,
        )
        await self._customer_repo.create_individual(individual)

        customer = Customer(
            id=customer_id,
            party_id=party_id,
            status="active",
            customer_since=now,
            tenant_id=ctx.tenant,
        )
        await self._customer_repo.create_customer(customer)

        for cm_data in contact_mediums:
            cm = ContactMedium(
                id=_next_id("CM"),
                party_id=party_id,
                medium_type=cm_data["medium_type"],
                value=cm_data["value"],
                is_primary=cm_data.get("is_primary", False),
                valid_from=now,
                tenant_id=ctx.tenant,
            )
            await self._customer_repo.create_contact_medium(cm)

        # --- Event ---
        await publisher.publish(
            self._session,
            event_type="customer.created",
            aggregate_type="customer",
            aggregate_id=customer_id,
            payload={"given_name": given_name, "family_name": family_name},
        )

        # --- Interaction auto-log ---
        await self._interaction_repo.create(
            Interaction(
                id=_next_id("INT"),
                customer_id=customer_id,
                channel=ctx.channel,
                direction="inbound",
                summary=f"Customer created: {given_name} {family_name}",
                occurred_at=now,
                tenant_id=ctx.tenant,
            )
        )

        await self._session.commit()
        return customer

    async def get_customer(self, customer_id: str) -> Customer | None:
        return await self._customer_repo.get_with_party(customer_id)

    async def list_customers(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[Customer]:
        return await self._customer_repo.list_customers(
            status=status, limit=limit, offset=offset
        )

    async def update_customer(self, customer_id: str, **updates: str | None) -> Customer:
        cust = await self._customer_repo.get(customer_id)
        if not cust:
            from app.policies.base import PolicyViolation
            raise PolicyViolation(
                rule="customer.update.not_found",
                message=f"Customer {customer_id} not found",
                context={"customer_id": customer_id},
            )
        for k, v in updates.items():
            if hasattr(cust, k) and v is not None:
                setattr(cust, k, v)
        await self._customer_repo.update(cust)

        ctx = auth_context.current()
        await publisher.publish(
            self._session,
            event_type="customer.updated",
            aggregate_type="customer",
            aggregate_id=customer_id,
            payload={"fields_updated": list(updates.keys())},
        )
        await self._interaction_repo.create(
            Interaction(
                id=_next_id("INT"),
                customer_id=customer_id,
                channel=ctx.channel,
                direction="inbound",
                summary=f"Customer updated: {', '.join(updates.keys())}",
                occurred_at=datetime.now(timezone.utc),
                tenant_id=ctx.tenant,
            )
        )
        await self._session.commit()
        return cust

    async def add_contact_medium(
        self, customer_id: str, *, medium_type: str, value: str, is_primary: bool = False
    ) -> ContactMedium:
        cust = await self._customer_repo.get(customer_id)
        if not cust:
            from app.policies.base import PolicyViolation
            raise PolicyViolation(
                rule="customer.contact.not_found",
                message=f"Customer {customer_id} not found",
                context={"customer_id": customer_id},
            )
        if medium_type == "email":
            await customer_policies.check_email_unique(value, self._customer_repo)

        ctx = auth_context.current()
        cm = ContactMedium(
            id=_next_id("CM"),
            party_id=cust.party_id,
            medium_type=medium_type,
            value=value,
            is_primary=is_primary,
            valid_from=datetime.now(timezone.utc),
            tenant_id=ctx.tenant,
        )
        await self._customer_repo.create_contact_medium(cm)

        await publisher.publish(
            self._session,
            event_type="customer.contact_medium_added",
            aggregate_type="customer",
            aggregate_id=customer_id,
            payload={"medium_type": medium_type},
        )
        await self._interaction_repo.create(
            Interaction(
                id=_next_id("INT"),
                customer_id=customer_id,
                channel=ctx.channel,
                direction="inbound",
                summary=f"Contact medium added: {medium_type}",
                occurred_at=datetime.now(timezone.utc),
                tenant_id=ctx.tenant,
            )
        )
        await self._session.commit()
        return cm

    async def remove_contact_medium(self, customer_id: str, cm_id: str) -> None:
        cust = await self._customer_repo.get(customer_id)
        if not cust:
            from app.policies.base import PolicyViolation
            raise PolicyViolation(
                rule="customer.contact.not_found",
                message=f"Customer {customer_id} not found",
                context={"customer_id": customer_id},
            )
        cm = await self._customer_repo.get_contact_medium(cm_id)
        if not cm or cm.party_id != cust.party_id:
            from app.policies.base import PolicyViolation
            raise PolicyViolation(
                rule="customer.contact.medium_not_found",
                message=f"Contact medium {cm_id} not found for customer {customer_id}",
                context={"customer_id": customer_id, "cm_id": cm_id},
            )
        await self._customer_repo.delete_contact_medium(cm)

        ctx = auth_context.current()
        await publisher.publish(
            self._session,
            event_type="customer.contact_medium_removed",
            aggregate_type="customer",
            aggregate_id=customer_id,
            payload={"cm_id": cm_id},
        )
        await self._session.commit()
