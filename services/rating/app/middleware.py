import uuid

import structlog
from bss_clients import set_context
from bss_clients.errors import ServerError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import auth_context
from app.domain.rating import RatingError

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
        set_context(actor=actor, channel=channel, request_id=request_id)

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
        except RatingError as exc:
            log.warning("rating.error", message=str(exc))
            return JSONResponse(
                status_code=422,
                content={
                    "code": "RATING_ERROR",
                    "message": str(exc),
                },
            )
        except ServerError as exc:
            log.error("upstream.server_error", status=exc.status_code, detail=str(exc))
            return JSONResponse(
                status_code=500,
                content={"detail": "Upstream service error"},
            )
        response.headers["x-request-id"] = request_id
        log.info("request.end", status=response.status_code)
        return response
