"""KYC attestation service.

Receives signed attestations from channel layer.
Hashes document_number immediately — NEVER stores or logs plaintext.
"""

import hashlib
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_context
from app.events import publisher
from app.policies import kyc as kyc_policies
from app.repositories.customer_repo import CustomerRepository
from app.repositories.interaction_repo import InteractionRepository
from app.repositories.kyc_repo import KycRepository
from bss_models.crm import CustomerIdentity, Interaction

log = structlog.get_logger()

from uuid import uuid4


def _next_int_id() -> str:
    return f"INT-{uuid4().hex[:8]}"


class KycService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        customer_repo: CustomerRepository,
        kyc_repo: KycRepository,
        interaction_repo: InteractionRepository,
    ) -> None:
        self._session = session
        self._customer_repo = customer_repo
        self._kyc_repo = kyc_repo
        self._interaction_repo = interaction_repo

    async def attest(
        self,
        customer_id: str,
        *,
        provider: str,
        provider_reference: str,
        document_type: str,
        document_number: str,
        document_country: str,
        date_of_birth: str,
        nationality: str | None = None,
        verified_at: str,
        attestation_payload: dict,
    ) -> dict:
        ctx = auth_context.current()

        # --- Policies ---
        await kyc_policies.check_customer_exists(customer_id, self._customer_repo)
        kyc_policies.check_attestation_signature(attestation_payload)

        # Hash document number IMMEDIATELY — plaintext never stored or logged
        document_number_hash = hashlib.sha256(document_number.encode()).hexdigest()
        # From this point, document_number is dead. We do NOT pass it anywhere else.

        await kyc_policies.check_document_hash_unique(
            document_type, document_number_hash, self._kyc_repo
        )

        # --- Write ---
        from datetime import date as date_type

        now = datetime.now(timezone.utc)
        identity = CustomerIdentity(
            customer_id=customer_id,
            document_type=document_type,
            document_number_hash=document_number_hash,
            document_country=document_country,
            date_of_birth=date_type.fromisoformat(date_of_birth),
            nationality=nationality,
            verified_by=provider,
            attestation_payload=attestation_payload,
            verified_at=datetime.fromisoformat(verified_at),
            tenant_id=ctx.tenant,
        )
        await self._kyc_repo.create(identity)

        # Update customer KYC status
        cust = await self._customer_repo.get(customer_id)
        cust.kyc_status = "verified"
        cust.kyc_verified_at = now
        cust.kyc_verification_method = provider
        cust.kyc_reference = provider_reference
        await self._customer_repo.update(cust)

        # --- Event (NEVER include plaintext document_number) ---
        await publisher.publish(
            self._session,
            event_type="customer.kyc_attested",
            aggregate_type="customer",
            aggregate_id=customer_id,
            payload={
                "provider": provider,
                "document_type": document_type,
                "document_country": document_country,
                "kyc_status": "verified",
            },
        )

        # --- Interaction auto-log ---
        await self._interaction_repo.create(
            Interaction(
                id=_next_int_id(),
                customer_id=customer_id,
                channel=ctx.channel,
                direction="inbound",
                summary=f"KYC attested via {provider}",
                occurred_at=now,
                tenant_id=ctx.tenant,
            )
        )

        await self._session.commit()

        return {
            "customer_id": customer_id,
            "kyc_status": "verified",
            "provider": provider,
            "verified_at": now.isoformat(),
        }

    async def get_status(self, customer_id: str) -> dict:
        cust = await self._customer_repo.get(customer_id)
        if not cust:
            from app.policies.base import PolicyViolation
            raise PolicyViolation(
                rule="customer.kyc.not_found",
                message=f"Customer {customer_id} not found",
                context={"customer_id": customer_id},
            )
        return {
            "customer_id": customer_id,
            "kyc_status": cust.kyc_status,
            "kyc_verified_at": cust.kyc_verified_at.isoformat() if cust.kyc_verified_at else None,
            "kyc_verification_method": cust.kyc_verification_method,
            "kyc_reference": cust.kyc_reference,
        }
