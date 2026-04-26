"""In-memory signup session store.

A signup spans three requests: the POST that triggers the agent, the
GET that opens the SSE stream, and any HTMX polls the progress page
fires. They all need to share the form input + the agent's emitted
state (subscription id, activation code, final AI text).

Production portals would put this in Redis. v0.4 is a demo — one
process, one dict, TTL-bounded. If the process restarts mid-signup
the user loses their session; that's an acceptable constraint per
V0_4_0.md §3 ("If they refresh during signup, it's gone").

Thread/async safety: protected by a single ``asyncio.Lock`` so
``create_session`` / ``get_session`` / ``update_session`` can be
called from route handlers without race-in-place on the dict. No
cross-process sharing; scaling beyond one replica requires swapping
this module for Redis.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass
class SignupSession:
    """All state for one in-flight signup.

    ``card_pan`` is held in memory for the short window between form
    submission and ``payment.add_card`` running through the mock
    tokenizer. We never persist it to disk — TTL-bounded RAM only —
    and the redacted ``card_pan_last4`` is what any log line or
    template ever sees. Production would tokenize at the edge and
    never hand the raw PAN to the portal process at all.
    """

    session_id: str
    plan: str
    name: str
    email: str
    phone: str
    msisdn: str  # chosen on the picker page; passed to order.create as msisdn_preference
    card_pan: str  # in-memory only, cleared once the agent finishes
    card_pan_last4: str
    # v0.8 — portal-auth identity that owns this signup. Pinned at the
    # POST /signup step from request.state.identity (the verified-email
    # session). The agent stream calls link_to_customer(identity_id,
    # customer_id) the moment customer.create returns a CUST-* id, so
    # the binding survives even if the customer abandons mid-flow.
    identity_id: str | None = None
    created_at: float = field(default_factory=monotonic)

    # Populated as the agent streams:
    customer_id: str | None = None
    order_id: str | None = None
    subscription_id: str | None = None
    activation_code: str | None = None
    final_text: str = ""
    error: str | None = None
    done: bool = False

    # One entry per streamed agent event, shaped like RenderedEvent's
    # dict (``kind`` / ``icon`` / ``title`` / ``detail`` / ``detail_full``
    # / ``is_error``). The confirmation page replays this list as static
    # HTML instead of reopening the SSE stream, so done sessions don't
    # retrigger the agent and don't get the "complete ✓ complete ✓"
    # reconnect spam.
    event_log: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    """TTL-bounded in-memory dict of SignupSession keyed by session_id."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, SignupSession] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        plan: str,
        name: str,
        email: str,
        phone: str,
        msisdn: str,
        card_pan: str,
        identity_id: str | None = None,
    ) -> SignupSession:
        session_id = uuid.uuid4().hex
        session = SignupSession(
            session_id=session_id,
            plan=plan,
            name=name,
            email=email,
            phone=phone,
            msisdn=msisdn,
            card_pan=card_pan,
            card_pan_last4=card_pan[-4:],
            identity_id=identity_id,
        )
        async with self._lock:
            self._prune_locked()
            self._items[session_id] = session
        return session

    async def get(self, session_id: str) -> SignupSession | None:
        async with self._lock:
            self._prune_locked()
            return self._items.get(session_id)

    async def update(self, session: SignupSession) -> None:
        async with self._lock:
            self._items[session.session_id] = session

    def _prune_locked(self) -> None:
        cutoff = monotonic() - self._ttl
        expired = [sid for sid, s in self._items.items() if s.created_at < cutoff]
        for sid in expired:
            self._items.pop(sid, None)
