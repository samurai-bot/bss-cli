"""Natural-language prompt templates for portal-triggered agent flows.

Kept in a dedicated module so the prompt is (a) grep-able, (b) snapshotable
in tests, and (c) tunable without touching route handlers. v0.4 has one
flow — signup. v0.5+ adds more (CSR-triggered plan change, etc.) here.
"""

from __future__ import annotations

# Pre-baked Myinfo attestation — simulated "✓ Identity verified" badge.
# The displayed attestation ID is stable (KYC-PREBAKED-001) so the
# signup form reads consistently, but the actual signature passed to
# ``customer.attest_kyc`` is derived per customer because the CRM's
# ``customer.attest_kyc.document_hash_unique_per_tenant`` policy
# rejects duplicate documents (one Myinfo identity = one customer).
# See DECISIONS.md 2026-04-23 for the rationale.
KYC_PREBAKED_ATTESTATION_ID = "KYC-PREBAKED-001"
KYC_PREBAKED_SIGNATURE_TEMPLATE = "myinfo-simulated-prebaked-v1::{email}"


def _signature_for(email: str) -> str:
    return KYC_PREBAKED_SIGNATURE_TEMPLATE.format(email=email)


def signup_prompt(
    *,
    name: str,
    email: str,
    phone: str,
    plan: str,
    msisdn: str,
    card_pan: str,
) -> str:
    """Build the NL instruction the agent sees when a signup form is submitted.

    The phrasing deliberately lists steps in order and asks for the
    final subscription + activation details. The agent plans the tool
    chain from this; we do not enumerate tool names (that would be
    back-channel imperative programming in prose).
    """
    signature = _signature_for(email)
    return (
        f"A new customer just completed the self-serve signup form. "
        f"Please: "
        f"(1) create a customer named '{name}' with email '{email}' and phone '{phone}'; "
        f"(2) attest their KYC using the pre-verified Myinfo attestation "
        f"with signature '{signature}' "
        f"and attestation id '{KYC_PREBAKED_ATTESTATION_ID}'; "
        f"(3) add card {card_pan} as their payment method on file; "
        f"(4) place an order for offering '{plan}', passing msisdn_preference='{msisdn}' "
        f"so the customer gets the number they picked on the portal; "
        f"(5) wait for the order to reach 'completed' and report the "
        f"resulting subscription id plus the eSIM activation code."
    )
