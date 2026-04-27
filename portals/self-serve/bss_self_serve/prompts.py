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

    Phrasing notes (v0.10 hardening — Gemma 4 was truncating after step 3):

    * Lead with the success criterion (return a SUB-* + LPA code), not a
      step list. The model anchors on "what does done look like" before
      it plans the chain.
    * Steps are framed as prerequisites for the success criterion, not
      a checklist with optional terminations. The "I am NOT done until"
      clause makes the system prompt's "Stop when the job is done" rule
      resolve to the FULL chain rather than the first numbered item.
    * No tool names — the agent plans the chain from semantics. Putting
      tool names in the prose is back-channel imperative programming
      and creates brittleness when the tool surface evolves.
    """
    signature = _signature_for(email)
    return (
        f"A new customer just completed the self-serve signup form. "
        f"You are NOT done until you have an active subscription with an "
        f"id like 'SUB-XXXX' and you've returned both the subscription "
        f"id AND the eSIM activation code. Adding a payment method on "
        f"file is NOT enough; placing an order is NOT enough; you must "
        f"wait for the order to reach 'completed' state and report the "
        f"resulting SUB-* id + LPA activation code. "
        f"To get there, do all of: "
        f"(1) create a customer named '{name}' with email '{email}' and phone '{phone}'; "
        f"(2) attest their KYC using the pre-verified Myinfo attestation "
        f"with signature '{signature}' "
        f"and attestation id '{KYC_PREBAKED_ATTESTATION_ID}'; "
        f"(3) add card {card_pan} as their payment method on file; "
        f"(4) place an order for offering '{plan}', passing msisdn_preference='{msisdn}' "
        f"so the customer gets the number they picked on the portal; "
        f"(5) wait for the order to reach 'completed' "
        f"(use the polling tool — the order activation is asynchronous "
        f"and takes ~1 second). "
        f"The activation code lives on the resulting subscription. "
        f"If any step fails with a structured error, follow the "
        f"suggested recovery and continue — do not stop until you have "
        f"the SUB-* id and the LPA code."
    )
