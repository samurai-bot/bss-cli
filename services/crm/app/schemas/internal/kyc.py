"""KYC attestation DTOs."""

from pydantic import BaseModel


class KycAttestationRequest(BaseModel):
    provider: str
    provider_reference: str
    document_type: str
    document_number: str
    document_country: str
    date_of_birth: str
    nationality: str | None = None
    verified_at: str
    attestation_payload: dict


class KycStatusResponse(BaseModel):
    customer_id: str
    kyc_status: str
    kyc_verified_at: str | None = None
    kyc_verification_method: str | None = None
    kyc_reference: str | None = None
