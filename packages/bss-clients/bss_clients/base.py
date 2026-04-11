"""BSSClient base — httpx.AsyncClient with timeouts, typed errors, auth hook.

Design rules:
- Timeouts are mandatory and per-method. Default 5s, overridable per call.
- No automatic retries. A 503 is a fact — the caller decides.
- Typed errors: NotFound ≠ ServerError ≠ PolicyViolationFromServer.
- Header propagation: X-BSS-Actor, X-BSS-Channel, X-Request-ID from context.
- AuthProvider called on every outgoing request.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

import httpx

from .auth import AuthProvider, NoAuthProvider
from .errors import ClientError, NotFound, PolicyViolationFromServer, ServerError, Timeout

# Context headers are injected by the calling service's middleware.
# bss-clients reads them from a ContextVar so cross-service calls propagate
# the original actor/channel/request-id.
_actor_var: ContextVar[str] = ContextVar("bss_actor", default="system")
_channel_var: ContextVar[str] = ContextVar("bss_channel", default="system")
_request_id_var: ContextVar[str] = ContextVar("bss_request_id", default="")


def set_context(*, actor: str, channel: str, request_id: str) -> None:
    """Called by service middleware to propagate context to outgoing calls."""
    _actor_var.set(actor)
    _channel_var.set(channel)
    _request_id_var.set(request_id)


class BSSClient:
    """Base HTTP client for service-to-service calls."""

    def __init__(
        self,
        base_url: str,
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth_provider or NoAuthProvider()
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})

        # Auth headers from provider
        auth_headers = await self._auth.get_headers()
        headers.update(auth_headers)

        # Context headers — propagate actor/channel/request-id across hops
        headers.setdefault("X-BSS-Actor", _actor_var.get())
        headers.setdefault("X-BSS-Channel", _channel_var.get())
        request_id = _request_id_var.get() or str(uuid.uuid4())
        headers.setdefault("X-Request-ID", request_id)

        kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout

        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise Timeout(f"{method} {path} timed out")

        return await self._handle_response(resp)

    async def _handle_response(self, resp: httpx.Response) -> httpx.Response:
        if resp.status_code == 404:
            raise NotFound(resp.text)

        if resp.status_code == 422:
            try:
                body = resp.json()
            except Exception:
                raise ClientError(422, resp.text)
            if body.get("code") == "POLICY_VIOLATION":
                raise PolicyViolationFromServer(
                    rule=body["reason"],
                    message=body["message"],
                    context=body.get("context", {}),
                )
            raise ClientError(422, resp.text)

        if resp.status_code >= 500:
            raise ServerError(resp.status_code, resp.text)

        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BSSClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
