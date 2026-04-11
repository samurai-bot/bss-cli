"""KYC attestation intake endpoints."""

import structlog
from fastapi import APIRouter, Depends

from app.dependencies import get_kyc_service
from app.schemas.internal.kyc import KycAttestationRequest, KycStatusResponse
from app.services.kyc_service import KycService

log = structlog.get_logger()

router = APIRouter(tags=["KYC"])


@router.post("/customer/{customer_id}/kyc-attestation", status_code=200)
async def attest_kyc(
    customer_id: str,
    body: KycAttestationRequest,
    svc: KycService = Depends(get_kyc_service),
) -> dict:
    # Log the attestation attempt — structlog redaction will strip document_number
    log.info(
        "kyc.attestation.received",
        customer_id=customer_id,
        provider=body.provider,
        document_type=body.document_type,
        document_number=body.document_number,
    )
    result = await svc.attest(
        customer_id,
        provider=body.provider,
        provider_reference=body.provider_reference,
        document_type=body.document_type,
        document_number=body.document_number,
        document_country=body.document_country,
        date_of_birth=body.date_of_birth,
        nationality=body.nationality,
        verified_at=body.verified_at,
        attestation_payload=body.attestation_payload,
    )
    return result


@router.get("/customer/{customer_id}/kyc-status", response_model=KycStatusResponse)
async def get_kyc_status(
    customer_id: str,
    svc: KycService = Depends(get_kyc_service),
) -> KycStatusResponse:
    result = await svc.get_status(customer_id)
    return KycStatusResponse(**result)
