"""FastAPI app factory for the CSR (customer service rep) portal.

Per V0_5_0.md §9 + §Security model:
- ``BSSApiTokenMiddleware`` is NOT on the portal's inbound HTTP. The
  stub login is the inbound gate (cookie-based; not real auth — see
  Phase 12). Outbound calls to BSS services carry ``BSS_API_TOKEN``
  via the orchestrator's existing ``TokenAuthProvider`` wiring.
- ``configure_telemetry(service_name="portal-csr")`` runs in lifespan
  so portal spans surface in ``bss trace``.
- The shared ``bss-portal-ui`` package owns the agent log widget +
  vendored HTMX + base CSS, mounted at ``/portal-ui/static/``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bss_portal_ui import STATIC_DIR as SHARED_STATIC_DIR
from bss_telemetry import configure_telemetry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .deps import install_redirect_handler
from .session import OperatorSessionStore

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = app.state.settings
    configure_telemetry(service_name="portal-csr", app=app)
    app.state.session_store = OperatorSessionStore(
        ttl_seconds=settings.bss_portal_csr_session_ttl,
    )
    log.info("portal.starting", service=settings.service_name)
    yield
    log.info("portal.stopping", service=settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(
        title=f"BSS-CLI {settings.service_name}",
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_redirect_handler(app)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount(
        "/portal-ui/static",
        StaticFiles(directory=SHARED_STATIC_DIR),
        name="portal-ui-static",
    )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": settings.service_name,
                "version": settings.version,
            }
        )

    from .routes import agent_events, ask, auth, case, customer, search

    app.include_router(auth.router)
    app.include_router(search.router)
    app.include_router(customer.router)
    app.include_router(case.router)
    app.include_router(ask.router)
    app.include_router(agent_events.router)

    return app


app = create_app
