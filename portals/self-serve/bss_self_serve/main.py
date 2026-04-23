"""FastAPI app factory for the self-serve portal.

Per V0_4_0.md §8:
- ``BSSApiTokenMiddleware`` is NOT on the portal's inbound HTTP. It's a
  public-facing surface (signup page); nothing protects it except
  network-level exposure control. See the V0_4_0.md §Security model.
- The portal's OUTBOUND calls to services DO carry ``X-BSS-API-Token``
  via the orchestrator's existing ``get_clients()`` factory and via
  any ad-hoc read clients the routes construct.
- ``configure_telemetry(service_name="portal-self-serve")`` runs in
  lifespan so portal spans show up in ``bss trace``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bss_telemetry import configure_telemetry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .session import SessionStore

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = app.state.settings
    # Portal telemetry — same bootstrap as the 9 services. No
    # validate_api_token_present() call because the portal itself
    # doesn't require the token inbound; outbound calls read it lazily
    # when constructing bss-clients via the orchestrator factory.
    configure_telemetry(service_name="portal-self-serve", app=app)
    app.state.session_store = SessionStore(
        ttl_seconds=settings.bss_portal_self_serve_session_ttl,
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

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": settings.service_name,
                "version": settings.version,
            }
        )

    from .routes import (
        activation,
        agent_events,
        confirmation,
        landing,
        session_api,
        signup,
    )

    app.include_router(landing.router)
    app.include_router(signup.router)
    app.include_router(activation.router)
    app.include_router(confirmation.router)
    app.include_router(agent_events.router)
    app.include_router(session_api.router)

    return app


# Uvicorn entry point: ``portal-self-serve = bss_self_serve.main:app``
# but since we need create_app(), the Dockerfile calls with --factory.
app = create_app
