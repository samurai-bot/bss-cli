"""Dependencies — lifespan, session factory, DI providers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from bss_clients import (
    CatalogClient,
    CRMClient,
    NoAuthProvider,
    PaymentClient,
    SOMClient,
    SubscriptionClient,
)
from bss_telemetry import configure_telemetry
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.events.consumer import setup_consumer
from app.repositories.order_repo import OrderRepository
from app.services.order_service import OrderService

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    configure_telemetry(service_name="com", app=app)
    engine = create_async_engine(settings.db_url, pool_size=5, max_overflow=5)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.mq_exchange = None
    app.state.mq_connection = None

    # Service-to-service clients
    crm_client = CRMClient(
        base_url=settings.crm_url,
        auth_provider=NoAuthProvider(),
    )
    catalog_client = CatalogClient(
        base_url=settings.catalog_url,
        auth_provider=NoAuthProvider(),
    )
    payment_client = PaymentClient(
        base_url=settings.payment_url,
        auth_provider=NoAuthProvider(),
    )
    som_client = SOMClient(
        base_url=settings.som_url,
        auth_provider=NoAuthProvider(),
    )
    subscription_client = SubscriptionClient(
        base_url=settings.subscription_url,
        auth_provider=NoAuthProvider(),
    )

    app.state.crm_client = crm_client
    app.state.catalog_client = catalog_client
    app.state.payment_client = payment_client
    app.state.som_client = som_client
    app.state.subscription_client = subscription_client

    # Set up MQ consumer (non-blocking — logs warning if MQ not configured)
    try:
        await setup_consumer(app)
    except Exception:
        log.warning("mq.consumer.setup_failed", exc_info=True)

    log.info("service.starting", service=settings.service_name)
    yield
    log.info("service.stopping", service=settings.service_name)

    # Teardown
    if app.state.mq_connection:
        try:
            await app.state.mq_connection.close()
        except Exception:
            log.warning("mq.connection.close_failed", exc_info=True)

    await crm_client.close()
    await catalog_client.close()
    await payment_client.close()
    await som_client.close()
    await subscription_client.close()
    await engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_order_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrderService:
    return OrderService(
        session=session,
        repo=OrderRepository(session),
        crm_client=request.app.state.crm_client,
        catalog_client=request.app.state.catalog_client,
        payment_client=request.app.state.payment_client,
        som_client=request.app.state.som_client,
        subscription_client=request.app.state.subscription_client,
        exchange=request.app.state.mq_exchange,
    )
