"""Customer + Party + Individual + ContactMedium + Agent repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bss_models.crm import (
    Agent,
    ContactMedium,
    Customer,
    Individual,
    Party,
)


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── Customer ────────────────────────────────────────────────────

    async def get(self, customer_id: str) -> Customer | None:
        stmt = (
            select(Customer)
            .options(
                selectinload(Customer.identity),
                selectinload(Customer.cases),
                selectinload(Customer.tickets),
            )
            .where(Customer.id == customer_id)
        )
        result = await self._s.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_party(self, customer_id: str) -> Customer | None:
        stmt = (
            select(Customer)
            .options(selectinload(Customer.identity))
            .where(Customer.id == customer_id)
        )
        result = await self._s.execute(stmt)
        cust = result.scalar_one_or_none()
        if cust:
            # Eager-load party + individual + contacts
            party_stmt = (
                select(Party)
                .options(
                    selectinload(Party.individual),
                    selectinload(Party.contact_mediums),
                )
                .where(Party.id == cust.party_id)
            )
            party_result = await self._s.execute(party_stmt)
            cust._party = party_result.scalar_one_or_none()
        return cust

    async def list_customers(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[Customer]:
        stmt = select(Customer).limit(limit).offset(offset).order_by(Customer.id)
        if status:
            stmt = stmt.where(Customer.status == status)
        result = await self._s.execute(stmt)
        return list(result.scalars().all())

    async def find_by_email(self, email: str) -> Customer | None:
        stmt = (
            select(Customer)
            .join(Party, Customer.party_id == Party.id)
            .join(ContactMedium, ContactMedium.party_id == Party.id)
            .where(
                ContactMedium.medium_type == "email",
                ContactMedium.value == email,
                ContactMedium.valid_to.is_(None),
            )
        )
        result = await self._s.execute(stmt)
        return result.scalar_one_or_none()

    async def create_party(self, party: Party) -> Party:
        self._s.add(party)
        await self._s.flush()
        return party

    async def create_individual(self, individual: Individual) -> Individual:
        self._s.add(individual)
        await self._s.flush()
        return individual

    async def create_customer(self, customer: Customer) -> Customer:
        self._s.add(customer)
        await self._s.flush()
        return customer

    async def update(self, customer: Customer) -> Customer:
        await self._s.flush()
        return customer

    # ── Contact Medium ──────────────────────────────────────────────

    async def create_contact_medium(self, cm: ContactMedium) -> ContactMedium:
        self._s.add(cm)
        await self._s.flush()
        return cm

    async def get_contact_medium(self, cm_id: str) -> ContactMedium | None:
        result = await self._s.execute(
            select(ContactMedium).where(ContactMedium.id == cm_id)
        )
        return result.scalar_one_or_none()

    async def get_contact_mediums_for_party(self, party_id: str) -> list[ContactMedium]:
        result = await self._s.execute(
            select(ContactMedium)
            .where(ContactMedium.party_id == party_id, ContactMedium.valid_to.is_(None))
            .order_by(ContactMedium.id)
        )
        return list(result.scalars().all())

    async def delete_contact_medium(self, cm: ContactMedium) -> None:
        await self._s.delete(cm)
        await self._s.flush()

    # ── Agent ───────────────────────────────────────────────────────

    async def get_agent(self, agent_id: str) -> Agent | None:
        result = await self._s.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_agents(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Agent]:
        stmt = select(Agent).limit(limit).offset(offset).order_by(Agent.id)
        if status:
            stmt = stmt.where(Agent.status == status)
        result = await self._s.execute(stmt)
        return list(result.scalars().all())
