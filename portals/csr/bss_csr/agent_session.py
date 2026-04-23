"""In-memory store for in-flight CSR agent asks.

One ``AgentAsk`` per ask submission — keyed by a random session_id
the SSE stream uses to look it up. Holds the operator's question +
target customer + the running event log so the customer 360 page
can render any state the agent leaves behind.

Distinct from ``OperatorSession`` (cookie-keyed login state); both
live in their own stores on app.state.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass
class AgentAsk:
    session_id: str
    operator_id: str
    customer_id: str
    question: str
    created_at: float = field(default_factory=monotonic)
    done: bool = False
    error: str | None = None
    final_text: str = ""
    event_log: list[dict[str, Any]] = field(default_factory=list)


class AgentAskStore:
    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, AgentAsk] = {}
        self._lock = asyncio.Lock()

    async def create(
        self, *, operator_id: str, customer_id: str, question: str
    ) -> AgentAsk:
        ask = AgentAsk(
            session_id=uuid.uuid4().hex,
            operator_id=operator_id,
            customer_id=customer_id,
            question=question,
        )
        async with self._lock:
            self._prune_locked()
            self._items[ask.session_id] = ask
        return ask

    async def get(self, session_id: str) -> AgentAsk | None:
        async with self._lock:
            self._prune_locked()
            return self._items.get(session_id)

    def _prune_locked(self) -> None:
        cutoff = monotonic() - self._ttl
        expired = [sid for sid, a in self._items.items() if a.created_at < cutoff]
        for sid in expired:
            self._items.pop(sid, None)
