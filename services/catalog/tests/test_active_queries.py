"""v0.7 — active-aware catalog queries.

Exercises time-bound row filtering, lowest-active-wins on overlapping
prices, and the no-active-row policy violation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bss_catalog.policies import PolicyViolation
from bss_catalog.repository import CatalogRepository


_SCRUB_SQL = [
    "DELETE FROM catalog.product_offering_price WHERE id LIKE 'TEST_PRICE_%'",
    "DELETE FROM catalog.product_offering WHERE id LIKE 'TEST_OFFERING_%'",
    # Defensive: catalog_versioning_and_plan_change.yaml seeds these under
    # runs that don't currently tear down catalog rows. The active-price
    # tests `t0=2026-02-15` overlaps the scenario's promo window, so leftovers
    # would silently win the lowest-active lookup. Scrub before AND after.
    "DELETE FROM catalog.product_offering_price WHERE id LIKE 'PRICE_PLAN_M_CNY_%'",
    "DELETE FROM catalog.product_offering_price WHERE id LIKE 'PRICE_PLAN_L_V2_%'",
]


@pytest.fixture
async def write_session(settings):
    """Per-test write session committed live; cleanup via teardown SQL."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for stmt in _SCRUB_SQL:
            await session.execute(text(stmt))
        await session.commit()
    async with factory() as session:
        yield session
    async with factory() as session:
        for stmt in _SCRUB_SQL:
            await session.execute(text(stmt))
        await session.commit()
    await engine.dispose()


@pytest.fixture
def t0() -> datetime:
    """Reference moment used across the time-bound tests."""
    return datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestGetActivePrice:
    async def test_unbounded_seed_price_is_active_now(self, write_session: AsyncSession):
        """Seed prices have valid_from=valid_to=NULL → always active."""
        repo = CatalogRepository(write_session)
        price = await repo.get_active_price("PLAN_M")
        assert price.id == "PRICE_PLAN_M"
        assert float(price.amount) == 25.00

    async def test_lowest_active_wins_during_overlap(
        self, write_session: AsyncSession, t0: datetime
    ):
        """Promo $20 + base $25 both active → caller charged $20."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering_price
                (id, offering_id, price_type, recurring_period_length,
                 recurring_period_type, amount, currency, valid_from, valid_to)
            VALUES ('TEST_PRICE_PLAN_M_PROMO', 'PLAN_M', 'recurring', 1, 'month',
                    20.00, 'SGD', :start, :end)
        """), {"start": t0 - timedelta(days=5), "end": t0 + timedelta(days=5)})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        price = await repo.get_active_price("PLAN_M", at=t0)
        assert price.id == "TEST_PRICE_PLAN_M_PROMO"
        assert float(price.amount) == 20.00

    async def test_promo_outside_window_falls_back_to_base(
        self, write_session: AsyncSession, t0: datetime
    ):
        """Past valid_to → only base price is active."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering_price
                (id, offering_id, price_type, recurring_period_length,
                 recurring_period_type, amount, currency, valid_from, valid_to)
            VALUES ('TEST_PRICE_PLAN_M_PROMO', 'PLAN_M', 'recurring', 1, 'month',
                    20.00, 'SGD', :start, :end)
        """), {"start": t0 - timedelta(days=10), "end": t0 - timedelta(days=1)})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        price = await repo.get_active_price("PLAN_M", at=t0)
        assert price.id == "PRICE_PLAN_M"

    async def test_exact_valid_from_boundary_is_inclusive(
        self, write_session: AsyncSession, t0: datetime
    ):
        """At exactly valid_from, the row is active."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering_price
                (id, offering_id, price_type, recurring_period_length,
                 recurring_period_type, amount, currency, valid_from, valid_to)
            VALUES ('TEST_PRICE_PLAN_M_PROMO', 'PLAN_M', 'recurring', 1, 'month',
                    20.00, 'SGD', :start, :end)
        """), {"start": t0, "end": t0 + timedelta(days=5)})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        price = await repo.get_active_price("PLAN_M", at=t0)
        assert price.id == "TEST_PRICE_PLAN_M_PROMO"

    async def test_exact_valid_to_boundary_is_exclusive(
        self, write_session: AsyncSession, t0: datetime
    ):
        """At exactly valid_to, the row is NO LONGER active."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering_price
                (id, offering_id, price_type, recurring_period_length,
                 recurring_period_type, amount, currency, valid_from, valid_to)
            VALUES ('TEST_PRICE_PLAN_M_PROMO', 'PLAN_M', 'recurring', 1, 'month',
                    20.00, 'SGD', :start, :end)
        """), {"start": t0 - timedelta(days=5), "end": t0})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        price = await repo.get_active_price("PLAN_M", at=t0)
        assert price.id == "PRICE_PLAN_M"

    async def test_no_active_row_raises_policy_violation(
        self, write_session: AsyncSession, t0: datetime
    ):
        """Offering with no recurring price at all → structured error."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering
                (id, name, spec_id, is_bundle, is_sellable, lifecycle_status,
                 valid_from, valid_to)
            VALUES ('TEST_OFFERING_BARE', 'Bare', 'SPEC_MOBILE_PREPAID',
                    true, true, 'active', NULL, NULL)
        """))
        await write_session.commit()

        repo = CatalogRepository(write_session)
        with pytest.raises(PolicyViolation) as exc_info:
            await repo.get_active_price("TEST_OFFERING_BARE", at=t0)
        assert exc_info.value.rule == "catalog.price.no_active_row"
        assert exc_info.value.context["offering_id"] == "TEST_OFFERING_BARE"


class TestListActiveOfferings:
    async def test_seeded_three_plans_at_now(self, write_session: AsyncSession):
        repo = CatalogRepository(write_session)
        offerings = await repo.list_active_offerings()
        ids = [o.id for o in offerings]
        # All three seed plans are sellable + lifecycle=active + unbounded.
        assert {"PLAN_S", "PLAN_M", "PLAN_L"}.issubset(set(ids))
        # Order: PLAN_S ($10) before PLAN_M ($25) before PLAN_L ($45).
        s_idx = ids.index("PLAN_S")
        m_idx = ids.index("PLAN_M")
        l_idx = ids.index("PLAN_L")
        assert s_idx < m_idx < l_idx

    async def test_promo_offering_outside_window_excluded(
        self, write_session: AsyncSession, t0: datetime
    ):
        """A windowed offering before its valid_from is not in the list."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering
                (id, name, spec_id, is_bundle, is_sellable, lifecycle_status,
                 valid_from, valid_to)
            VALUES ('TEST_OFFERING_CNY', 'CNY Promo', 'SPEC_MOBILE_PREPAID',
                    true, true, 'active', :start, :end)
        """), {"start": t0 + timedelta(days=10), "end": t0 + timedelta(days=20)})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        # Before the window — excluded.
        offerings = await repo.list_active_offerings(at=t0)
        assert "TEST_OFFERING_CNY" not in {o.id for o in offerings}
        # Inside the window — included.
        offerings = await repo.list_active_offerings(at=t0 + timedelta(days=15))
        assert "TEST_OFFERING_CNY" in {o.id for o in offerings}


class TestGetOfferingPriceById:
    async def test_direct_lookup_ignores_time_filter(
        self, write_session: AsyncSession, t0: datetime
    ):
        """Snapshot resolve fetches a row even if it's no longer active."""
        await write_session.execute(text("""
            INSERT INTO catalog.product_offering_price
                (id, offering_id, price_type, recurring_period_length,
                 recurring_period_type, amount, currency, valid_from, valid_to)
            VALUES ('TEST_PRICE_PLAN_M_RETIRED', 'PLAN_M', 'recurring', 1, 'month',
                    18.00, 'SGD', :start, :end)
        """), {"start": t0 - timedelta(days=100), "end": t0 - timedelta(days=10)})
        await write_session.commit()

        repo = CatalogRepository(write_session)
        price = await repo.get_offering_price_by_id("TEST_PRICE_PLAN_M_RETIRED")
        assert price is not None
        assert float(price.amount) == 18.00

    async def test_unknown_id_returns_none(self, write_session: AsyncSession):
        repo = CatalogRepository(write_session)
        price = await repo.get_offering_price_by_id("PRICE_DOES_NOT_EXIST")
        assert price is None
