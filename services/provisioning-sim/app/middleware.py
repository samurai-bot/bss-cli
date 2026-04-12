"""Request middleware — header propagation, policy error handling."""

import uuid

import structlog
from bss_clients import set_context
from bss_clients.errors import ServerError
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import auth_context
from app.policies.base import PolicyViolation

log = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        actor = request.headers.get("x-bss-actor", "system")
        channel = request.headers.get("x-bss-channel", "system")
        tenant = request.headers.get("x-bss-tenant", "DEFAULT")

        auth_context.set_for_request(actor=actor, channel=channel, tenant=tenant)
        set_context(actor=actor, channel=channel, request_id=request_id)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            actor=actor,
            channel=channel,
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)
        except PolicyViolation as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "POLICY_VIOLATION",
                    "reason": exc.rule,
                    "message": exc.message,
                    "referenceError": f"https://docs.bss-cli.dev/policies/{exc.rule}",
                    "context": exc.context,
                },
            )
        except ServerError as exc:
            log.error("upstream.error", status=exc.status_code, detail=exc.detail)
            return JSONResponse(
                status_code=500,
                content={"detail": "Upstream service error"},
            )

        response.headers["X-Request-ID"] = request_id
        return response
