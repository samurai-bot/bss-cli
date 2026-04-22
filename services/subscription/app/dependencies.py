from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from bss_clients import (
    CatalogClient,
    CRMClient,
    InventoryClient,
    NoAuthProvider,
    PaymentClient,
)
from bss_telemetry import configure_telemetry
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.events.consumer import setup_consumer
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.vas_repo import VasPurchaseRepository
from app.services.subscription_service import SubscriptionService

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    configure_telemetry(service_name="subscription")
    engine = create_async_engine(settings.db_url, pool_size=5, max_overflow=5)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.mq_exchange = None
    app.state.mq_connection = None
    app.state.crm_client = CRMClient(
        base_url=settings.crm_url, auth_provider=NoAuthProvider()
    )
    app.state.payment_client = PaymentClient(
        base_url=settings.payment_url, auth_provider=NoAuthProvider()
    )
    app.state.catalog_client = CatalogClient(
        base_url=settings.catalog_url, auth_provider=NoAuthProvider()
    )
    app.state.inventory_client = InventoryClient(
        base_url=settings.crm_url, auth_provider=NoAuthProvider()
    )

    try:
        await setup_consumer(app)
    except Exception:
        log.warning("mq.consumer.setup_failed", exc_info=True)

    log.info("service.starting", service=settings.service_name)
    yield
    log.info("service.stopping", service=settings.service_name)

    if app.state.mq_connection:
        try:
            await app.state.mq_connection.close()
        except Exception:
            log.warning("mq.connection.close_failed", exc_info=True)

    await app.state.crm_client.close()
    await app.state.payment_client.close()
    await app.state.catalog_client.close()
    await app.state.inventory_client.close()
    await engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_subscription_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SubscriptionService:
    return SubscriptionService(
        session=session,
        repo=SubscriptionRepository(session),
        vas_repo=VasPurchaseRepository(session),
        crm_client=request.app.state.crm_client,
        payment_client=request.app.state.payment_client,
        catalog_client=request.app.state.catalog_client,
        inventory_client=request.app.state.inventory_client,
    )
