"""Pure ASGI middleware: require X-BSS-API-Token on every BSS request.

Behavior (per V0_3_0.md §1a):

1. Path in EXEMPT_PATHS → pass through (no auth).
2. ``X-BSS-API-Token`` header missing → 401 ``AUTH_MISSING_TOKEN``.
3. Header present but mismatch → 401 ``AUTH_INVALID_TOKEN``. Comparison
   uses ``hmac.compare_digest`` (timing-safe).
4. Header matches → pass through.

The middleware is registered after RequestIdMiddleware in each service's
main.py so that auth runs first (Starlette ``add_middleware`` prepends:
last-added = outermost). The OTel server span (set up by
FastAPIInstrumentor) wraps everything including auth — 401s show up
in Jaeger as 401 spans, which is the correct behavior for ops triage.

Log policy: per ``(remote_addr, path)`` pair, the first 401 inside a
60-second window is logged at INFO; subsequent 401s in the same
window are silent. Avoids log spam from probes or misconfigured
clients without losing visibility into a fresh failure mode.
"""

from __future__ import annotations

import hmac
import json
import time
from typing import Final

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings

log = structlog.get_logger(__name__)

EXEMPT_PATHS: Final[frozenset[str]] = frozenset({
    "/health",
    "/health/ready",
    "/health/live",
})

AUTH_MISSING_TOKEN: Final[str] = "AUTH_MISSING_TOKEN"
AUTH_INVALID_TOKEN: Final[str] = "AUTH_INVALID_TOKEN"

_LOG_THROTTLE_SECONDS = 60.0


class BSSApiTokenMiddleware:
    def __init__(self, app: ASGIApp, *, token: str | None = None) -> None:
        self.app = app
        self._token = (token or Settings().BSS_API_TOKEN).encode()
        self._token_str = self._token.decode()
        # In-process throttle dict: (remote_addr, path) -> last log timestamp.
        self._last_logged: dict[tuple[str, str], float] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        provided = _extract_header(scope, b"x-bss-api-token")
        if not provided:
            self._log_throttled(scope, path, reason="missing")
            await _send_401_json(send, AUTH_MISSING_TOKEN, "X-BSS-API-Token header required")
            return

        if not hmac.compare_digest(provided.encode(), self._token):
            self._log_throttled(scope, path, reason="wrong")
            await _send_401_json(send, AUTH_INVALID_TOKEN, "invalid API token")
            return

        await self.app(scope, receive, send)

    def _log_throttled(self, scope: Scope, path: str, *, reason: str) -> None:
        client = scope.get("client") or ("unknown", 0)
        remote = client[0] if isinstance(client, (tuple, list)) else "unknown"
        key = (remote, path)
        now = time.monotonic()
        last = self._last_logged.get(key)
        if last is not None and (now - last) < _LOG_THROTTLE_SECONDS:
            return
        self._last_logged[key] = now
        log.info("auth.401", reason=reason, remote=remote, path=path)


def _extract_header(scope: Scope, name: bytes) -> str | None:
    """Read a single header value from the ASGI scope. Case-insensitive name match."""
    target = name.lower()
    for k, v in scope.get("headers", []):
        if k.lower() == target:
            return v.decode("latin-1")
    return None


async def _send_401_json(send: Send, code: str, message: str) -> None:
    body = json.dumps({"code": code, "message": message}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})
