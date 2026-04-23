"""In-memory operator session store for the stub login.

Per V0_5_0.md §3 + §Security model — the login is NOT a security
control. It populates ``X-BSS-Actor`` so the audit trail attributes
agent-driven actions to a human operator. Real auth ships in
Phase 12; this exists so the demo has someone to point at on the
interaction log.

Cookie ``bss_csr_session`` carries a UUID token; the store maps
token → ``OperatorSession`` (just the operator_id). TTL-bounded
RAM, lost on restart. Cross-process scaling = swap for Redis;
out-of-scope for v0.5.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from time import monotonic


@dataclass
class OperatorSession:
    token: str
    operator_id: str
    created_at: float = field(default_factory=monotonic)


class OperatorSessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, OperatorSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, *, operator_id: str) -> OperatorSession:
        token = secrets.token_urlsafe(24)
        session = OperatorSession(token=token, operator_id=operator_id)
        async with self._lock:
            self._prune_locked()
            self._items[token] = session
        return session

    async def get(self, token: str) -> OperatorSession | None:
        async with self._lock:
            self._prune_locked()
            return self._items.get(token)

    async def delete(self, token: str) -> None:
        async with self._lock:
            self._items.pop(token, None)

    def _prune_locked(self) -> None:
        cutoff = monotonic() - self._ttl
        expired = [t for t, s in self._items.items() if s.created_at < cutoff]
        for t in expired:
            self._items.pop(t, None)


SESSION_COOKIE = "bss_csr_session"
