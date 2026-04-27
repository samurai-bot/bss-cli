"""FastAPI app factory for the self-serve portal.

Per V0_4_0.md §8 / V0_8_0.md §2.2:

- ``BSSApiTokenMiddleware`` is NOT on the portal's inbound HTTP. The
  portal is a customer-facing surface protected by the v0.8 portal-auth
  layer (PortalSessionMiddleware below). Outbound calls carry the
  portal's named token via ``bss_self_serve.clients.get_clients()``
  (v0.9+: ``BSS_PORTAL_SELF_SERVE_API_TOKEN`` → ``service_identity = "portal_self_serve"``
  on the receiving side; falls back to ``BSS_API_TOKEN`` if the named
  token is not provisioned).
- ``configure_telemetry(service_name="portal-self-serve")`` runs in
  lifespan so portal spans show up in ``bss trace``.
- v0.8 lifespan adds:
    * ``validate_pepper_present()`` — fail fast if BSS_PORTAL_TOKEN_PEPPER
      is unset / sentinel / too short.
    * ``app.state.db_engine`` + ``app.state.db_session_factory`` — async
      engine reading ``BSS_DB_URL``. The session middleware and security
      deps both pull the factory off ``app.state``.
    * ``app.state.email_adapter`` — selected via
      ``BSS_PORTAL_EMAIL_ADAPTER`` env (logging | noop | smtp-stub).
    * ``PortalSessionMiddleware`` is mounted on the FastAPI app so it
      runs on every request before route resolution.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bss_portal_auth import (
    Settings as PortalAuthSettings,
    select_adapter,
    validate_pepper_present,
)
from bss_portal_ui import STATIC_DIR as SHARED_STATIC_DIR
from bss_telemetry import configure_telemetry
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import Settings
from .middleware import PortalSessionMiddleware
from .security import install_redirect_handlers
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

    # v0.8 — portal-auth startup checks BEFORE any auth flow can run.
    validate_pepper_present()

    # v0.8 — DB engine for portal_auth identity / session storage.
    # Optional: if BSS_DB_URL is unset (e.g. unit-test app construction
    # without a DB), middleware fails open (logs once and passes through).
    portal_auth_settings = PortalAuthSettings()
    if settings.bss_db_url:
        engine = create_async_engine(settings.bss_db_url, pool_size=5, max_overflow=5)
        app.state.db_engine = engine
        app.state.db_session_factory = async_sessionmaker(
            engine, expire_on_commit=False
        )
    else:
        app.state.db_engine = None
        app.state.db_session_factory = None
        log.warning("portal.db_url.missing")

    # v0.8 — email adapter selection. LoggingEmailAdapter writes to a
    # file the operator can `tail -f`; NoopEmailAdapter is for tests;
    # 'smtp' raises at construction (reserved for v1.0).
    app.state.email_adapter = select_adapter(
        portal_auth_settings.BSS_PORTAL_EMAIL_ADAPTER,
        portal_auth_settings.BSS_PORTAL_DEV_MAILBOX_PATH,
    )

    app.state.session_store = SessionStore(
        ttl_seconds=settings.bss_portal_self_serve_session_ttl,
    )
    log.info(
        "portal.starting",
        service=settings.service_name,
        email_adapter=portal_auth_settings.BSS_PORTAL_EMAIL_ADAPTER,
        db_url_set=bool(settings.bss_db_url),
    )
    yield
    log.info("portal.stopping", service=settings.service_name)
    if app.state.db_engine is not None:
        await app.state.db_engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(
        title=f"BSS-CLI {settings.service_name}",
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # v0.8 — session middleware runs on every request. Pure ASGI so SSE
    # streams (/agent/events/{session_id}) keep working. Mounted via
    # add_middleware so it sits OUTSIDE the FastAPI router.
    app.add_middleware(PortalSessionMiddleware)

    # 303 redirect handlers for the gating dependencies in security.py.
    install_redirect_handlers(app)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    # Shared UI assets (vendored HTMX + base CSS) live in bss-portal-ui.
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

    from .routes import (
        activation,
        agent_events,
        auth,
        confirmation,
        esim,
        landing,
        msisdn_picker,
        payment_methods,
        session_api,
        signup,
        top_up,
        welcome,
    )

    app.include_router(auth.router)
    app.include_router(welcome.router)
    app.include_router(landing.router)
    app.include_router(msisdn_picker.router)
    app.include_router(signup.router)
    app.include_router(activation.router)
    app.include_router(confirmation.router)
    app.include_router(agent_events.router)
    app.include_router(session_api.router)
    # v0.10 — post-login self-serve writes go direct (no orchestrator).
    app.include_router(top_up.router)
    app.include_router(payment_methods.router)
    app.include_router(esim.router)

    return app


# Uvicorn entry point: ``portal-self-serve = bss_self_serve.main:app``
# but since we need create_app(), the Dockerfile calls with --factory.
app = create_app
