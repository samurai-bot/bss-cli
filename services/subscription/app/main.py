"""Subscription service — FastAPI app factory."""

from fastapi import FastAPI

from app.api import admin, health, subscription
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

    # Subscription API
    app.include_router(
        subscription.router,
        prefix="/subscription-api/v1",
    )

    # Admin — operational-data reset (gated by BSS_ALLOW_ADMIN_RESET)
    app.include_router(admin.router, prefix="/admin-api/v1")

    return app
