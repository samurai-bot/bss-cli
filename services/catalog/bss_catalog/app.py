from fastapi import FastAPI

from bss_catalog.config import Settings
from bss_catalog.deps import lifespan
from bss_catalog.logging import configure_logging
from bss_catalog.middleware import RequestIdMiddleware
from bss_catalog.routes import health, product_offering, product_specification, vas


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
    app.include_router(
        product_offering.router,
        prefix="/tmf-api/productCatalogManagement/v4",
    )
    app.include_router(
        product_specification.router,
        prefix="/tmf-api/productCatalogManagement/v4",
    )
    app.include_router(vas.router, prefix="/vas")

    return app
