"""The single path from CSR route handlers into the LLM orchestrator.

Every write a CSR operator triggers goes through ``ask_about_customer``
which wraps ``bss_orchestrator.session.astream_once``. Route handlers
never call mutating bss-clients methods — the agent is the only path
to making changes from the CSR portal.

Pinning ``allow_destructive=False`` is the one in-band guardrail still
standing while the stub login is the only inbound auth (per
V0_5_0.md §Security model). Channel ``portal-csr`` + actor
``<operator_id>`` set the X-BSS-Channel + X-BSS-Actor headers on every
outbound bss-clients call so the interaction log attributes the work
to the human, not to ``llm-<model-slug>``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from bss_orchestrator.clients import get_clients
from bss_orchestrator.session import AgentEvent, astream_once

from .prompts import build_csr_prompt


async def _customer_snapshot(customer_id: str) -> dict[str, Any]:
    raw = await get_clients().crm.get_customer(customer_id)
    individual = raw.get("individual") or {}
    name = " ".join(
        s for s in [individual.get("givenName"), individual.get("familyName")] if s
    ).strip() or customer_id
    contacts = raw.get("contactMedium") or []
    email = next(
        (c["value"] for c in contacts if c.get("mediumType") == "email"), ""
    )
    return {
        "name": name,
        "email": email,
        "status": raw.get("status", "?"),
        "kyc_status": raw.get("kycStatus", "?"),
    }


async def _subscription_snapshot(customer_id: str) -> list[dict[str, Any]]:
    subs = await get_clients().subscription.list_for_customer(customer_id)
    return [
        {
            "id": s.get("id", "?"),
            "state": s.get("state", "?"),
            "offering": s.get("offeringId", "?"),
        }
        for s in (subs or [])
    ]


async def ask_about_customer(
    *,
    customer_id: str,
    question: str,
    operator_id: str,
) -> AsyncIterator[AgentEvent]:
    """Drive a CSR-initiated agent turn and yield each AgentEvent."""
    customer_snapshot = await _customer_snapshot(customer_id)
    subscription_snapshot = await _subscription_snapshot(customer_id)
    prompt = build_csr_prompt(
        operator_id=operator_id,
        customer_id=customer_id,
        question=question,
        customer_snapshot=customer_snapshot,
        subscription_snapshot=subscription_snapshot,
    )
    async for event in astream_once(
        prompt,
        allow_destructive=False,
        channel="portal-csr",
        actor=operator_id,
    ):
        yield event
