"""Payment service — FastAPI app factory."""

from fastapi import FastAPI

from app.api import health
from app.api.tmf import payment, payment_method
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

    # TMF676 Payment Method Management
    app.include_router(
        payment_method.router,
        prefix="/tmf-api/paymentMethodManagement/v4",
    )

    # TMF676 Payment Management
    app.include_router(
        payment.router,
        prefix="/tmf-api/paymentManagement/v4",
    )

    return app
