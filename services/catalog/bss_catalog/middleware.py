import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from bss_catalog import auth_context

log = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        actor = request.headers.get("x-bss-actor", "system")
        channel = request.headers.get("x-bss-channel", "system")
        tenant = request.headers.get("x-bss-tenant", "DEFAULT")

        auth_context.set_for_request(actor=actor, tenant=tenant, channel=channel)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            actor=actor,
            channel=channel,
            method=request.method,
            path=request.url.path,
        )

        log.info("request.start")
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        log.info("request.end", status=response.status_code)
        return response
