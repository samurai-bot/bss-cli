"""SOM (Service Order Management) — FastAPI app factory."""

from fastapi import FastAPI

from app.api import health, service, service_order
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

    # TMF641 — ServiceOrder
    app.include_router(
        service_order.router,
        prefix="/tmf-api/serviceOrderingManagement/v4",
    )

    # TMF638 — Service Inventory
    app.include_router(
        service.router,
        prefix="/tmf-api/serviceInventoryManagement/v4",
    )

    return app
