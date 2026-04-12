"""PaymentService — orchestration for charge attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import structlog
from bss_clock import now as clock_now
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_context
from app.domain import mock_tokenizer
from app.events import publisher
from app.policies import payment as pay_policies
from app.policies.base import PolicyViolation
from app.repositories.payment_attempt_repo import PaymentAttemptRepository
from app.repositories.payment_method_repo import PaymentMethodRepository
from bss_models import PaymentAttempt

log = structlog.get_logger()


class PaymentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        attempt_repo: PaymentAttemptRepository,
        pm_repo: PaymentMethodRepository,
    ) -> None:
        self._session = session
        self._attempt_repo = attempt_repo
        self._pm_repo = pm_repo

    async def charge(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        amount: Decimal,
        currency: str = "SGD",
        purpose: str,
    ) -> PaymentAttempt:
        ctx = auth_context.current()

        # --- Load method ---
        method = await self._pm_repo.get(payment_method_id)
        if method is None:
            raise PolicyViolation(
                rule="payment.charge.method_not_found",
                message=f"Payment method {payment_method_id} not found",
                context={"payment_method_id": payment_method_id},
            )

        # --- Policies ---
        pay_policies.check_method_active(method)
        pay_policies.check_positive_amount(amount)
        pay_policies.check_customer_matches_method(customer_id, method)

        # --- Execute charge via mock gateway ---
        attempt_id = await self._attempt_repo.next_id()
        now = clock_now()

        charge_result = await mock_tokenizer.charge(
            method.token, amount, currency
        )

        attempt = PaymentAttempt(
            id=attempt_id,
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            amount=amount,
            currency=currency,
            purpose=purpose,
            status=charge_result.status,
            gateway_ref=charge_result.gateway_ref,
            decline_reason=charge_result.reason,
            attempted_at=now,
            tenant_id=ctx.tenant,
        )
        await self._attempt_repo.create(attempt)

        # --- Event ---
        event_type = {
            "approved": "payment.charged",
            "declined": "payment.declined",
        }.get(charge_result.status, "payment.errored")

        await publisher.publish(
            self._session,
            event_type=event_type,
            aggregate_type="payment_attempt",
            aggregate_id=attempt_id,
            payload={
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "amount": str(amount),
                "currency": currency,
                "purpose": purpose,
                "status": charge_result.status,
                "gateway_ref": charge_result.gateway_ref,
            },
        )

        await self._session.commit()
        log.info(
            f"payment.{charge_result.status}",
            attempt_id=attempt_id,
            amount=str(amount),
            purpose=purpose,
        )
        return attempt

    async def get_attempt(self, attempt_id: str) -> PaymentAttempt | None:
        return await self._attempt_repo.get(attempt_id)

    async def list_attempts(self, customer_id: str) -> list[PaymentAttempt]:
        return await self._attempt_repo.list_for_customer(customer_id)
