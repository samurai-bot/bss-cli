import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import auth_context
from app.policies.base import PolicyViolation

log = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
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
        try:
            response = await call_next(request)
        except PolicyViolation as exc:
            log.warning(
                "policy.violation",
                rule=exc.rule,
                message=exc.message,
                context=exc.context,
            )
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
        response.headers["x-request-id"] = request_id
        log.info("request.end", status=response.status_code)
        return response
