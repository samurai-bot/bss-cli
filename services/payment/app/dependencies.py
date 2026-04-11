from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from bss_clients import CRMClient, NoAuthProvider
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.repositories.payment_attempt_repo import PaymentAttemptRepository
from app.repositories.payment_method_repo import PaymentMethodRepository
from app.services.payment_method_service import PaymentMethodService
from app.services.payment_service import PaymentService

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    engine = create_async_engine(settings.db_url, pool_size=5, max_overflow=5)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.crm_client = CRMClient(
        base_url=settings.crm_url,
        auth_provider=NoAuthProvider(),
    )
    log.info("service.starting", service=settings.service_name)
    yield
    log.info("service.stopping", service=settings.service_name)
    await app.state.crm_client.close()
    await engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


# ── Repositories ────────────────────────────────────────────────────


async def get_pm_repo(
    session: AsyncSession = Depends(get_session),
) -> PaymentMethodRepository:
    return PaymentMethodRepository(session)


async def get_attempt_repo(
    session: AsyncSession = Depends(get_session),
) -> PaymentAttemptRepository:
    return PaymentAttemptRepository(session)


# ── Services ────────────────────────────────────────────────────────


async def get_payment_method_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PaymentMethodService:
    return PaymentMethodService(
        session=session,
        pm_repo=PaymentMethodRepository(session),
        crm_client=request.app.state.crm_client,
    )


async def get_payment_service(
    session: AsyncSession = Depends(get_session),
) -> PaymentService:
    return PaymentService(
        session=session,
        attempt_repo=PaymentAttemptRepository(session),
        pm_repo=PaymentMethodRepository(session),
    )
