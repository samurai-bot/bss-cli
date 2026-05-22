from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from bss_clients import BearerAuthProvider, LoyaltyClient
from bss_middleware import validate_api_token_present
from bss_telemetry import configure_telemetry
from fastapi import Depends, FastAPI, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bss_catalog.promotion_repository import PromotionRepository
from bss_catalog.promotion_service import PromotionService
from bss_catalog.repository import CatalogRepository

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    validate_api_token_present()  # fail-fast on misconfig
    settings = app.state.settings
    configure_telemetry(service_name="catalog", app=app)
    engine = create_async_engine(settings.db_url, pool_size=5, max_overflow=5)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # v1.1 — the LoyaltyClient lives here; its token never leaves this process.
    # Empty token fails fast at BearerAuthProvider construction (clearer than a
    # 401 on first use) — set BSS_LOYALTY_API_TOKEN. Generate: openssl rand -hex 32.
    if not settings.loyalty_api_token:
        raise RuntimeError(
            "BSS_LOYALTY_API_TOKEN is unset — catalog holds the loyalty-cli "
            "client for v1.1 promotions. Generate with: openssl rand -hex 32"
        )
    app.state.loyalty_client = LoyaltyClient(
        base_url=settings.loyalty_base_url,
        auth_provider=BearerAuthProvider(settings.loyalty_api_token),
    )

    log.info("service.starting", service=settings.service_name)
    yield
    log.info("service.stopping", service=settings.service_name)
    await app.state.loyalty_client.close()
    await engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_repo(session: AsyncSession = Depends(get_session)) -> CatalogRepository:
    return CatalogRepository(session)


async def get_promotion_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
    x_bss_actor: str = Header(default="anonymous"),
) -> PromotionService:
    return PromotionService(
        session=session,
        repo=PromotionRepository(session),
        loyalty=request.app.state.loyalty_client,
        actor=x_bss_actor,
    )
