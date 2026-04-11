"""KYC attestation policies."""

from app import auth_context
from app.policies.base import PolicyViolation, policy
from app.repositories.customer_repo import CustomerRepository
from app.repositories.kyc_repo import KycRepository


@policy("customer.attest_kyc.customer_exists")
async def check_customer_exists(
    customer_id: str, repo: CustomerRepository
) -> None:
    cust = await repo.get(customer_id)
    if not cust:
        raise PolicyViolation(
            rule="customer.attest_kyc.customer_exists",
            message=f"Customer {customer_id} does not exist",
            context={"customer_id": customer_id},
        )


@policy("customer.attest_kyc.attestation_signature_valid")
def check_attestation_signature(attestation_payload: dict) -> None:
    # v0.1 stub: accept any payload with a `signature` field
    # Phase 12: real JWS validation against channel provider public keys
    if "signature" not in attestation_payload:
        raise PolicyViolation(
            rule="customer.attest_kyc.attestation_signature_valid",
            message="Attestation payload missing signature",
            context={},
        )


@policy("customer.attest_kyc.document_hash_unique_per_tenant")
async def check_document_hash_unique(
    document_type: str, document_number_hash: str, kyc_repo: KycRepository
) -> None:
    ctx = auth_context.current()
    existing = await kyc_repo.find_by_document_hash(
        tenant_id=ctx.tenant,
        document_type=document_type,
        document_number_hash=document_number_hash,
    )
    if existing:
        raise PolicyViolation(
            rule="customer.attest_kyc.document_hash_unique_per_tenant",
            message="This identity document is already registered",
            context={"document_type": document_type},
        )
