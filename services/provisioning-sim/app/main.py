"""Provisioning simulator — FastAPI app factory."""

from fastapi import FastAPI

from app.api import fault_injection, health, task
from app.config import Settings
from app.dependencies import lifespan
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=f"BSS-CLI {settings.service_name}",
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(RequestIdMiddleware)

    # Health
    app.include_router(health.router)

    # Provisioning API
    app.include_router(
        task.router,
        prefix="/provisioning-api/v1",
    )
    app.include_router(
        fault_injection.router,
        prefix="/provisioning-api/v1",
    )

    return app
