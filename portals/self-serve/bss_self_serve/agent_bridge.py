"""The single path from portal route handlers into the LLM orchestrator.

Every *write* a portal user makes goes through ``drive_signup`` (v0.4 has
no other write surfaces). Route handlers never import ``CustomerClient``,
``OrderClient``, or any other mutating bss-clients class — they call
``drive_signup`` and relay the resulting event stream into the SSE
response.

``astream_once`` is the orchestrator's streaming entry point (see
``orchestrator/bss_orchestrator/session.py``); it yields typed
``AgentEvent`` dataclasses. Pinning ``allow_destructive=False`` is the
one in-band guardrail we have before Phase 12 ships real per-principal
auth. Do not remove the pin. ``channel="portal-self-serve"`` sets the
``X-BSS-Channel`` header on every outbound bss-clients call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from bss_orchestrator.session import AgentEvent, astream_once

from .prompts import signup_prompt


async def drive_signup(
    *,
    name: str,
    email: str,
    phone: str,
    plan: str,
    card_pan: str,
) -> AsyncIterator[AgentEvent]:
    """Drive a portal signup through the LLM agent and yield each event."""
    prompt = signup_prompt(
        name=name,
        email=email,
        phone=phone,
        plan=plan,
        card_pan=card_pan,
    )
    async for event in astream_once(
        prompt,
        allow_destructive=False,
        channel="portal-self-serve",
    ):
        yield event
