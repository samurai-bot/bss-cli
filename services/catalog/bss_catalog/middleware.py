"""Request middleware — pure ASGI to preserve contextvar propagation.

BaseHTTPMiddleware runs the inner app in a separate asyncio task,
breaking ContextVar propagation including OTel's current span
context. Pure ASGI middleware preserves it.
"""

import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bss_catalog import auth_context

log = structlog.get_logger()


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        actor = headers.get("x-bss-actor", "system")
        channel = headers.get("x-bss-channel", "system")
        tenant = headers.get("x-bss-tenant", "DEFAULT")

        auth_context.set_for_request(actor=actor, tenant=tenant, channel=channel)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            actor=actor,
            channel=channel,
            method=scope.get("method", "?"),
            path=scope.get("path", "?"),
        )

        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message.get("status", 0)
                headers_list = list(message.get("headers", []))
                headers_list.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers_list}
            await send(message)

        log.info("request.start")
        await self.app(scope, receive, send_wrapper)
        log.info("request.end", status=status_holder["status"])
