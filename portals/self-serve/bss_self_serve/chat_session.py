"""In-memory store for in-flight customer chat turns (v0.12 PR7).

One ``ChatTurn`` per POST /chat/message — keyed by a random
session_id the SSE stream uses to look it up. Holds the customer's
question + the running event log so a browser reconnect can replay.

Per phases/V0_12_0.md §scope-out: v0.12 chat is one user turn → one
agent stream → one response. No cross-turn conversation memory; each
POST creates a fresh ChatTurn. v1.x revisits.

Distinct from PortalSession (cookie-keyed login state); both live in
their own stores on app.state.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass
class ChatTurn:
    session_id: str
    customer_id: str
    question: str
    created_at: float = field(default_factory=monotonic)
    done: bool = False
    error: str | None = None
    final_text: str = ""
    # The trip-wire's per-stream verdict — when set, the chat route
    # renders the generic safety message instead of the LLM's reply.
    ownership_violation: bool = False
    event_log: list[dict[str, Any]] = field(default_factory=list)


class ChatTurnStore:
    """Bounded TTL-evicted store. Single-process only; the chat
    surface is a low-throughput conversational path so a global
    asyncio.Lock-guarded dict is fine. v1.x can swap to Redis if
    multiple portal replicas land."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, ChatTurn] = {}
        self._lock = asyncio.Lock()

    async def create(self, *, customer_id: str, question: str) -> ChatTurn:
        turn = ChatTurn(
            session_id=uuid.uuid4().hex,
            customer_id=customer_id,
            question=question,
        )
        async with self._lock:
            self._prune_locked()
            self._items[turn.session_id] = turn
        return turn

    async def get(self, session_id: str) -> ChatTurn | None:
        async with self._lock:
            self._prune_locked()
            return self._items.get(session_id)

    def _prune_locked(self) -> None:
        cutoff = monotonic() - self._ttl
        expired = [sid for sid, t in self._items.items() if t.created_at < cutoff]
        for sid in expired:
            self._items.pop(sid, None)
