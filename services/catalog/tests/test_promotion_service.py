"""v1.1 — PromotionService.create_promotion two-system saga.

Runs against the live dev DB (like the other catalog write tests): unique
promotion ids + finally-cleanup. The LoyaltyClient is faked so the saga
logic is tested without touching the real loyalty-cli (no entitlement-ledger
pollution) — the LoyaltyClient's own contract is covered in bss-clients.
"""

import uuid
from decimal import Decimal

import pytest
from bss_clients import PolicyViolationFromServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bss_catalog.policies import PolicyViolation
from bss_catalog.promotion_repository import PromotionRepository
from bss_catalog.promotion_service import PromotionService


def _pid(prefix: str = "PROMO") -> str:
    return f"{prefix}_TEST_{uuid.uuid4().hex[:8].upper()}"


class FakeLoyalty:
    """Records calls; optionally raises a refusal on the first OD register."""

    def __init__(self, *, refuse: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self._refuse = refuse

    async def register_offer_definition(self, **kwargs):
        self.calls.append(("register_offer_definition", kwargs))
        if self._refuse:
            raise PolicyViolationFromServer(
                rule="offer_definition.register.duplicate",
                message="offer definition already exists",
                context={"source": "loyalty"},
            )
        return {"id": kwargs["definition_id"]}

    async def register_promo_code(self, **kwargs):
        self.calls.append(("register_promo_code", kwargs))
        return {"code": kwargs["code"]}

    def called(self, name: str) -> list[dict]:
        return [args for n, args in self.calls if n == name]


async def _cleanup(session: AsyncSession, *promotion_ids: str):
    await session.execute(
        text("DELETE FROM catalog.promotion WHERE id = ANY(:ids)"),
        {"ids": list(promotion_ids)},
    )
    await session.commit()


def _svc(session, loyalty, actor="admin"):
    return PromotionService(session, PromotionRepository(session), loyalty, actor)


class TestCreatePromotionTargeted:
    async def test_codeless_promo_goes_active_without_promo_code_register(
        self, db_session: AsyncSession
    ):
        pid = _pid("PROMO_VIP")
        loyalty = FakeLoyalty()
        try:
            promo = await _svc(db_session, loyalty).create_promotion(
                promotion_id=pid,
                discount_type="percent",
                discount_value=Decimal("20"),
                duration_kind="single",
            )
            assert promo.state == "active"
            assert promo.offer_definition_id == f"OD_{pid}"
            assert promo.code is None
            # targeted = codeless → OD registered, but NO promo code
            assert len(loyalty.called("register_offer_definition")) == 1
            assert loyalty.called("register_promo_code") == []
            # saga step 2 idempotency key is the promotion id
            assert loyalty.called("register_offer_definition")[0]["idempotency_key"] == pid
        finally:
            await _cleanup(db_session, pid)


class TestCreatePromotionNonTargeted:
    async def test_coded_promo_registers_code(self, db_session: AsyncSession):
        pid = _pid("PROMO_SUMMER")
        code = f"SUMMER_{uuid.uuid4().hex[:6].upper()}"
        loyalty = FakeLoyalty()
        try:
            promo = await _svc(db_session, loyalty).create_promotion(
                promotion_id=pid,
                discount_type="absolute",
                discount_value=Decimal("5.00"),
                duration_kind="multi",
                periods_total=3,
                code=code,
                promo_code_kind="multi_use",
            )
            assert promo.state == "active"
            assert promo.code == code
            assert promo.periods_total == 3
            reg = loyalty.called("register_promo_code")
            assert len(reg) == 1
            assert reg[0]["code"] == code
            assert reg[0]["offer_definition_id"] == f"OD_{pid}"
            assert reg[0]["kind"] == "multi_use"
        finally:
            await _cleanup(db_session, pid)


class TestSagaFailureLeavesPendingLink:
    async def test_loyalty_refusal_translates_and_row_stays_pending(
        self, db_session: AsyncSession
    ):
        pid = _pid("PROMO_FAIL")
        loyalty = FakeLoyalty(refuse=True)
        try:
            with pytest.raises(PolicyViolation) as exc:
                await _svc(db_session, loyalty).create_promotion(
                    promotion_id=pid,
                    discount_type="percent",
                    discount_value=Decimal("10"),
                    duration_kind="single",
                )
            assert exc.value.rule == "catalog.promotion.loyalty_refused"
            # row written but NOT confirmed — harmless, reconcilable
            row = await PromotionRepository(db_session).get(pid)
            assert row is not None
            assert row.state == "pending_link"
            assert row.offer_definition_id is None
        finally:
            await _cleanup(db_session, pid)

    async def test_retry_resumes_pending_link_to_active(self, db_session: AsyncSession):
        pid = _pid("PROMO_RESUME")
        try:
            # first attempt fails at loyalty
            with pytest.raises(PolicyViolation):
                await _svc(db_session, FakeLoyalty(refuse=True)).create_promotion(
                    promotion_id=pid,
                    discount_type="percent",
                    discount_value=Decimal("15"),
                    duration_kind="single",
                )
            # retry with a healthy loyalty resumes the same row (no duplicate)
            healthy = FakeLoyalty()
            promo = await _svc(db_session, healthy).create_promotion(
                promotion_id=pid,
                discount_type="percent",
                discount_value=Decimal("15"),
                duration_kind="single",
            )
            assert promo.state == "active"
            assert promo.offer_definition_id == f"OD_{pid}"
            assert len(await PromotionRepository(db_session).list(limit=1000)) >= 1
        finally:
            await _cleanup(db_session, pid)


class TestCreatePromotionGuards:
    async def test_active_promo_rejects_duplicate(self, db_session: AsyncSession):
        pid = _pid("PROMO_DUP")
        try:
            await _svc(db_session, FakeLoyalty()).create_promotion(
                promotion_id=pid,
                discount_type="percent",
                discount_value=Decimal("10"),
                duration_kind="single",
            )
            with pytest.raises(PolicyViolation) as exc:
                await _svc(db_session, FakeLoyalty()).create_promotion(
                    promotion_id=pid,
                    discount_type="percent",
                    discount_value=Decimal("10"),
                    duration_kind="single",
                )
            assert exc.value.rule == "catalog.promotion.already_exists"
        finally:
            await _cleanup(db_session, pid)

    async def test_duplicate_code_rejected(self, db_session: AsyncSession):
        pid1, pid2 = _pid("PROMO_C1"), _pid("PROMO_C2")
        code = f"DUP_{uuid.uuid4().hex[:6].upper()}"
        try:
            await _svc(db_session, FakeLoyalty()).create_promotion(
                promotion_id=pid1,
                discount_type="percent",
                discount_value=Decimal("10"),
                duration_kind="single",
                code=code,
                promo_code_kind="single_use_shared",
            )
            with pytest.raises(PolicyViolation) as exc:
                await _svc(db_session, FakeLoyalty()).create_promotion(
                    promotion_id=pid2,
                    discount_type="percent",
                    discount_value=Decimal("10"),
                    duration_kind="single",
                    code=code,
                    promo_code_kind="single_use_shared",
                )
            assert exc.value.rule == "catalog.promotion.code_in_use"
        finally:
            await _cleanup(db_session, pid1, pid2)

    @pytest.mark.parametrize(
        "kwargs,expected_rule",
        [
            (dict(discount_type="bogus", discount_value=Decimal("10"), duration_kind="single"),
             "catalog.promotion.invalid_discount_type"),
            (dict(discount_type="percent", discount_value=Decimal("150"), duration_kind="single"),
             "catalog.promotion.invalid_discount_value"),
            (dict(discount_type="percent", discount_value=Decimal("0"), duration_kind="single"),
             "catalog.promotion.invalid_discount_value"),
            (dict(discount_type="percent", discount_value=Decimal("10"), duration_kind="multi"),
             "catalog.promotion.invalid_periods_total"),
            (dict(discount_type="percent", discount_value=Decimal("10"), duration_kind="single", periods_total=3),
             "catalog.promotion.invalid_periods_total"),
            (dict(discount_type="percent", discount_value=Decimal("10"), duration_kind="single", code="X"),
             "catalog.promotion.invalid_promo_code_kind"),
        ],
    )
    async def test_validation_rejects(self, db_session: AsyncSession, kwargs, expected_rule):
        pid = _pid("PROMO_VAL")
        try:
            with pytest.raises(PolicyViolation) as exc:
                await _svc(db_session, FakeLoyalty()).create_promotion(promotion_id=pid, **kwargs)
            assert exc.value.rule == expected_rule
        finally:
            await _cleanup(db_session, pid)

    async def test_non_admin_actor_rejected(self, db_session: AsyncSession):
        pid = _pid("PROMO_AUTH")
        with pytest.raises(PolicyViolation) as exc:
            await _svc(db_session, FakeLoyalty(), actor="anonymous").create_promotion(
                promotion_id=pid,
                discount_type="percent",
                discount_value=Decimal("10"),
                duration_kind="single",
            )
        assert exc.value.rule == "catalog.admin_only"
