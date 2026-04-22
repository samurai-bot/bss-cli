from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from bss_telemetry import configure_telemetry
from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bss_catalog.repository import CatalogRepository

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = app.state.settings
    configure_telemetry(service_name="catalog")
    engine = create_async_engine(settings.db_url, pool_size=5, max_overflow=5)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    log.info("service.starting", service=settings.service_name)
    yield
    log.info("service.stopping", service=settings.service_name)
    await engine.dispose()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_repo(session: AsyncSession = Depends(get_session)) -> CatalogRepository:
    return CatalogRepository(session)
