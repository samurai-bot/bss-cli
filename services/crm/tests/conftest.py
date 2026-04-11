"""Test fixtures for CRM service.

Write isolation: every test runs inside a transaction that is rolled back
in teardown. session.commit() is monkeypatched to flush() so writes are
visible within the test but the outer transaction is never committed.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

from app.config import Settings
from app.logging import configure_logging
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = Settings()
    if not s.db_url:
        pytest.fail("BSS_DB_URL is not set. Export it or add to .env.")
    return s


@pytest.fixture(scope="session", autouse=True)
def _configure_logging(settings: Settings) -> None:
    configure_logging(settings.log_level)


@pytest_asyncio.fixture
async def db_engine(settings: Settings):
    engine = create_async_engine(settings.db_url, pool_size=2, max_overflow=2)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Per-test session wrapped in a transaction that is always rolled back.

    session.commit() is replaced with flush() so the service layer's commits
    don't escape the test transaction.
    """
    conn = await db_engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    # Monkeypatch: commit → flush (writes visible, but outer txn stays open)
    _original_commit = session.commit

    async def _fake_commit():
        await session.flush()

    session.commit = _fake_commit

    yield session

    await txn.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(settings: Settings, db_engine, db_session: AsyncSession):
    """ASGI test client wired to the rolled-back session."""
    app = create_app(settings)

    # Store engine on app.state for /ready endpoint
    app.state.engine = db_engine

    # Override the session factory so every request reuses the test session
    class _FakeSessionFactory:
        def __call__(self):
            return _FakeContextManager(db_session)

    class _FakeContextManager:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            pass

    app.state.session_factory = _FakeSessionFactory()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
