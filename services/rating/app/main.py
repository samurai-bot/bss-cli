"""Rating service — stateless pure rate_usage + usage.recorded → usage.rated."""

from fastapi import FastAPI

from app.api import health, rating
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

    app.include_router(health.router)
    app.include_router(rating.router, prefix="/rating-api/v1")

    return app
