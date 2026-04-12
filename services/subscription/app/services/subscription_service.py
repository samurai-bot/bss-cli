"""Subscription service — orchestration layer.

Router → Service → Policies → Repository → Event publisher.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import aio_pika
import structlog
from bss_clients import CatalogClient, CRMClient, InventoryClient, PaymentClient
from bss_clock import now as clock_now
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bundle import (
    AllowanceSpec,
    BalanceSnapshot,
    add_allowance,
    consume,
    is_exhausted,
    primary_allowance_type,
    reset_for_new_period,
)
from app.domain.state_machine import get_next_state, is_valid_transition
from app.events import publisher
from app.policies.base import PolicyViolation
from app.policies.subscription import (
    check_customer_exists,
    check_msisdn_and_esim_reserved,
    check_renew_allowed,
)
from app.policies.vas import check_not_terminated, check_vas_offering_sellable
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.vas_repo import VasPurchaseRepository
from bss_models.subscription import (
    BundleBalance,
    Subscription,
    SubscriptionStateHistory,
    VasPurchase,
)

log = structlog.get_logger()


class SubscriptionService:
    def __init__(
        self,
        session: AsyncSession,
        repo: SubscriptionRepository,
        vas_repo: VasPurchaseRepository,
        crm_client: CRMClient,
        payment_client: PaymentClient,
        catalog_client: CatalogClient,
        inventory_client: InventoryClient,
    ):
        self._session = session
        self._repo = repo
        self._vas_repo = vas_repo
        self._crm = crm_client
        self._payment = payment_client
        self._catalog = catalog_client
        self._inventory = inventory_client

    async def create(
        self,
        *,
        customer_id: str,
        offering_id: str,
        msisdn: str,
        iccid: str,
        payment_method_id: str,
    ) -> Subscription:
        # Policy: customer exists and is active/pending
        await check_customer_exists(customer_id, self._crm)

        # Policy: MSISDN and eSIM are reserved
        await check_msisdn_and_esim_reserved(msisdn, iccid, self._inventory)

        # Fetch offering from catalog for price + allowances
        offering = await self._catalog.get_offering(offering_id)
        prices = offering.get("productOfferingPrice", [])
        recurring = next((p for p in prices if p.get("priceType") == "recurring"), None)
        amount = Decimal(str(recurring["price"]["taxIncludedAmount"]["value"])) if recurring else Decimal("0")

        # Policy: payment must succeed
        payment_result = await self._payment.charge(
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            amount=amount,
            currency="SGD",
            purpose="activation",
        )
        if payment_result.get("status") != "approved":
            # Release inventory on payment failure
            try:
                await self._inventory.release_msisdn(msisdn)
            except Exception:
                log.warning("inventory.release_msisdn.failed", msisdn=msisdn)
            try:
                await self._inventory.recycle_esim(iccid)
            except Exception:
                log.warning("inventory.recycle_esim.failed", iccid=iccid[-4:])
            raise PolicyViolation(
                rule="subscription.create.requires_payment_success",
                message="Activation payment was declined",
                context={
                    "payment_status": payment_result.get("status"),
                    "decline_reason": payment_result.get("declineReason"),
                },
            )

        # Create subscription
        now = clock_now()
        period_end = now + timedelta(days=30)
        sub_id = await self._repo.next_id()

        sub = Subscription(
            id=sub_id,
            customer_id=customer_id,
            offering_id=offering_id,
            msisdn=msisdn,
            iccid=iccid,
            state="pending",
        )
        await self._repo.create(sub)

        # Initialize bundle balances from catalog allowances
        allowances = offering.get("bundleAllowance", [])
        for a in allowances:
            bal_id = f"{sub_id}-{a['allowanceType'].upper()}"
            balance = BundleBalance(
                id=bal_id,
                subscription_id=sub_id,
                allowance_type=a["allowanceType"],
                total=a["quantity"],
                consumed=0,
                unit=a["unit"],
                period_start=now,
                period_end=period_end,
            )
            await self._repo.add_balance(balance)

        # Assign inventory
        try:
            await self._inventory.assign_msisdn(msisdn)
        except Exception:
            log.warning("inventory.assign_msisdn.failed", msisdn=msisdn)
        try:
            await self._inventory.assign_msisdn_to_esim(iccid, msisdn)
        except Exception:
            log.warning("inventory.assign_esim.failed", iccid=iccid[-4:])

        # Transition: pending → active
        await self._transition(sub, "activate", reason="activation_payment_approved")
        sub.activated_at = now
        sub.current_period_start = now
        sub.current_period_end = period_end
        sub.next_renewal_at = period_end

        await publisher.publish(
            self._session,
            event_type="subscription.activated",
            aggregate_type="subscription",
            aggregate_id=sub_id,
            payload={
                "subscriptionId": sub_id,
                "customerId": customer_id,
                "offeringId": offering_id,
                "msisdn": msisdn,
                "iccid": iccid,
                "paymentAttemptId": payment_result.get("id", ""),
                "periodStart": now.isoformat(),
                "periodEnd": period_end.isoformat(),
            },
        )

        await self._session.commit()
        log.info("subscription.created", subscription_id=sub_id, state="active")

        # Reload to get balances
        sub = await self._repo.get(sub_id)
        return sub

    async def get(self, sub_id: str) -> Subscription | None:
        return await self._repo.get(sub_id)

    async def get_by_msisdn(self, msisdn: str) -> Subscription | None:
        return await self._repo.get_by_msisdn(msisdn)

    async def list_for_customer(self, customer_id: str) -> list[Subscription]:
        return await self._repo.list_for_customer(customer_id)

    async def get_balances(self, sub_id: str) -> list[BundleBalance]:
        return await self._repo.get_balances(sub_id)

    async def handle_usage_rated(
        self,
        *,
        subscription_id: str,
        allowance_type: str,
        consumed_quantity: int,
        usage_event_id: str,
        exchange: aio_pika.abc.AbstractExchange | None = None,
    ) -> None:
        """Process a `usage.rated` event.

        Concurrency: pessimistic lock via `SELECT ... FOR UPDATE` on the
        balance row so concurrent events for the same (subscription,
        allowance) serialize. See DECISIONS.md Phase 8 for why Option A
        was picked over optimistic locking or MQ partitioning.
        """
        sub = await self._repo.get(subscription_id)
        if not sub:
            log.warning(
                "usage.rated.subscription_not_found",
                subscription_id=subscription_id,
                usage_event_id=usage_event_id,
            )
            return

        # Belt-and-braces: Mediation rejects at ingress, but replays / races
        # can still deliver events for a non-active subscription. Drop them.
        if sub.state != "active":
            log.warning(
                "usage.rated.subscription_not_active",
                subscription_id=subscription_id,
                state=sub.state,
                usage_event_id=usage_event_id,
            )
            return

        target = await self._repo.get_balance_for_update(subscription_id, allowance_type)
        if target is None:
            log.warning(
                "usage.rated.allowance_not_on_subscription",
                subscription_id=subscription_id,
                allowance_type=allowance_type,
            )
            return

        snap = BalanceSnapshot(
            allowance_type=target.allowance_type,
            total=target.total,
            consumed=target.consumed,
            unit=target.unit,
        )
        result = consume(snap, consumed_quantity)
        target.consumed = result.consumed
        await self._repo.update_balance(target)

        all_balances = await self._repo.get_balances(subscription_id)
        snapshots = [
            BalanceSnapshot(
                allowance_type=b.allowance_type, total=b.total,
                consumed=b.consumed, unit=b.unit,
            )
            for b in all_balances
        ]

        if is_exhausted(snapshots):
            await publisher.publish(
                self._session,
                event_type="subscription.exhausted",
                aggregate_type="subscription",
                aggregate_id=subscription_id,
                payload={
                    "subscriptionId": subscription_id,
                    "allowanceType": allowance_type,
                    "consumed": result.consumed,
                    "total": result.total,
                    "triggeringUsageEventId": usage_event_id,
                },
                exchange=exchange,
            )
            await self._transition(sub, "exhaust", reason="primary_allowance_exhausted")
            await publisher.publish(
                self._session,
                event_type="subscription.blocked",
                aggregate_type="subscription",
                aggregate_id=subscription_id,
                payload={"subscriptionId": subscription_id, "reason": "exhausted"},
                exchange=exchange,
            )

        await self._session.commit()
        log.info(
            "usage.rated.applied",
            subscription_id=subscription_id,
            allowance_type=allowance_type,
            consumed_quantity=consumed_quantity,
            usage_event_id=usage_event_id,
            new_consumed=result.consumed,
            final_state=sub.state,
        )

    async def purchase_vas(
        self, sub_id: str, vas_offering_id: str
    ) -> Subscription:
        sub = await self._repo.get(sub_id)
        if not sub:
            raise PolicyViolation(
                rule="subscription.not_found",
                message=f"Subscription {sub_id} not found",
                context={"subscription_id": sub_id},
            )

        # Policies
        check_not_terminated(sub.state)

        vas = await check_vas_offering_sellable(vas_offering_id, self._catalog)

        # Charge payment
        # Find default payment method for customer
        methods = await self._payment.list_methods(sub.customer_id)
        default_method = next((m for m in methods if m.get("isDefault")), None)
        if not default_method:
            default_method = methods[0] if methods else None
        if not default_method:
            raise PolicyViolation(
                rule="subscription.vas_purchase.requires_active_cof",
                message="No active payment method found",
                context={"customer_id": sub.customer_id},
            )

        amount = Decimal(str(vas.get("priceAmount", 0)))
        payment_result = await self._payment.charge(
            customer_id=sub.customer_id,
            payment_method_id=default_method["id"],
            amount=amount,
            currency=vas.get("currency", "SGD"),
            purpose="vas",
        )
        if payment_result.get("status") != "approved":
            raise PolicyViolation(
                rule="subscription.vas_purchase.requires_active_cof",
                message="VAS payment was declined",
                context={
                    "payment_status": payment_result.get("status"),
                    "decline_reason": payment_result.get("declineReason"),
                },
            )

        # Record VAS purchase
        vas_id = f"{sub_id}-VAS-{uuid4().hex[:8].upper()}"
        now = clock_now()
        expiry_hours = vas.get("expiryHours")
        expires_at = now + timedelta(hours=expiry_hours) if expiry_hours else None
        allowance_qty = vas.get("allowanceQuantity", 0)
        allowance_type = vas.get("allowanceType", "data")

        purchase = VasPurchase(
            id=vas_id,
            subscription_id=sub_id,
            vas_offering_id=vas_offering_id,
            payment_attempt_id=payment_result.get("id"),
            applied_at=now,
            expires_at=expires_at,
            allowance_added=allowance_qty,
            allowance_type=allowance_type,
        )
        await self._vas_repo.create(purchase)

        # Add to balance
        balances = await self._repo.get_balances(sub_id)
        target = next((b for b in balances if b.allowance_type == allowance_type), None)
        if target and allowance_qty > 0 and target.total != -1:
            snap = BalanceSnapshot(
                allowance_type=target.allowance_type,
                total=target.total, consumed=target.consumed, unit=target.unit,
            )
            result = add_allowance(snap, allowance_qty)
            target.total = result.total
            await self._repo.update_balance(target)

        previous_state = sub.state

        await publisher.publish(
            self._session,
            event_type="subscription.vas_purchased",
            aggregate_type="subscription",
            aggregate_id=sub_id,
            payload={
                "subscriptionId": sub_id,
                "vasOfferingId": vas_offering_id,
                "paymentAttemptId": payment_result.get("id", ""),
                "allowanceType": allowance_type,
                "allowanceAdded": allowance_qty,
                "previousState": previous_state,
            },
        )

        # If blocked and top-up adds data → unblock
        if sub.state == "blocked":
            await self._transition(sub, "top_up", reason="vas_top_up")
            await publisher.publish(
                self._session,
                event_type="subscription.unblocked",
                aggregate_type="subscription",
                aggregate_id=sub_id,
                payload={"subscriptionId": sub_id, "reason": "vas_top_up"},
            )
        elif sub.state == "active":
            # top_up on active → still active (self-transition)
            await self._transition(sub, "top_up", reason="vas_top_up")

        await self._session.commit()
        return await self._repo.get(sub_id)

    async def renew(self, sub_id: str) -> Subscription:
        sub = await self._repo.get(sub_id)
        if not sub:
            raise PolicyViolation(
                rule="subscription.not_found",
                message=f"Subscription {sub_id} not found",
                context={"subscription_id": sub_id},
            )

        check_renew_allowed(sub.state)

        # Fetch offering for price + allowances
        offering = await self._catalog.get_offering(sub.offering_id)
        prices = offering.get("productOfferingPrice", [])
        recurring = next((p for p in prices if p.get("priceType") == "recurring"), None)
        amount = Decimal(str(recurring["price"]["taxIncludedAmount"]["value"])) if recurring else Decimal("0")

        # Find payment method
        methods = await self._payment.list_methods(sub.customer_id)
        default_method = next((m for m in methods if m.get("isDefault")), None)
        if not default_method:
            default_method = methods[0] if methods else None
        if not default_method:
            raise PolicyViolation(
                rule="subscription.renew.no_payment_method",
                message="No active payment method found for renewal",
                context={"customer_id": sub.customer_id},
            )

        payment_result = await self._payment.charge(
            customer_id=sub.customer_id,
            payment_method_id=default_method["id"],
            amount=amount,
            currency="SGD",
            purpose="renewal",
        )

        if payment_result.get("status") != "approved":
            # Renewal failed → block
            await self._transition(sub, "renew_fail", reason="renewal_payment_declined")
            await publisher.publish(
                self._session,
                event_type="subscription.renew_failed",
                aggregate_type="subscription",
                aggregate_id=sub_id,
                payload={
                    "subscriptionId": sub_id,
                    "reason": "payment_declined",
                    "paymentAttemptId": payment_result.get("id", ""),
                },
            )
            await publisher.publish(
                self._session,
                event_type="subscription.blocked",
                aggregate_type="subscription",
                aggregate_id=sub_id,
                payload={"subscriptionId": sub_id, "reason": "renew_failed"},
            )
            await self._session.commit()
            return await self._repo.get(sub_id)

        # Renewal succeeded — reset balances
        now = clock_now()
        period_end = now + timedelta(days=30)
        allowances = offering.get("bundleAllowance", [])
        specs = [
            AllowanceSpec(a["allowanceType"], a["quantity"], a["unit"])
            for a in allowances
        ]
        new_snapshots = reset_for_new_period(specs)

        # Update existing balances
        balances = await self._repo.get_balances(sub_id)
        for bal in balances:
            matching = next(
                (s for s in new_snapshots if s.allowance_type == bal.allowance_type),
                None,
            )
            if matching:
                bal.total = matching.total
                bal.consumed = 0
                bal.period_start = now
                bal.period_end = period_end
                await self._repo.update_balance(bal)

        await self._transition(sub, "renew", reason="renewal_payment_approved")
        sub.current_period_start = now
        sub.current_period_end = period_end
        sub.next_renewal_at = period_end

        await publisher.publish(
            self._session,
            event_type="subscription.renewed",
            aggregate_type="subscription",
            aggregate_id=sub_id,
            payload={
                "subscriptionId": sub_id,
                "offeringId": sub.offering_id,
                "paymentAttemptId": payment_result.get("id", ""),
                "periodStart": now.isoformat(),
                "periodEnd": period_end.isoformat(),
            },
        )

        await self._session.commit()
        return await self._repo.get(sub_id)

    async def terminate(self, sub_id: str) -> Subscription:
        sub = await self._repo.get(sub_id)
        if not sub:
            raise PolicyViolation(
                rule="subscription.not_found",
                message=f"Subscription {sub_id} not found",
                context={"subscription_id": sub_id},
            )

        if not is_valid_transition(sub.state, "terminate"):
            raise PolicyViolation(
                rule="subscription.terminate.invalid_state",
                message=f"Cannot terminate subscription in state '{sub.state}'",
                context={"state": sub.state},
            )

        now = clock_now()

        # Release inventory
        try:
            await self._inventory.release_msisdn(sub.msisdn)
        except Exception:
            log.warning("inventory.release_msisdn.failed", msisdn=sub.msisdn)

        try:
            await self._inventory.recycle_esim(sub.iccid)
        except Exception:
            log.warning("inventory.recycle_esim.failed", iccid=sub.iccid[-4:])

        await self._transition(sub, "terminate", reason="customer_requested")
        sub.terminated_at = now

        await publisher.publish(
            self._session,
            event_type="subscription.terminated",
            aggregate_type="subscription",
            aggregate_id=sub_id,
            payload={
                "subscriptionId": sub_id,
                "customerId": sub.customer_id,
                "msisdn": sub.msisdn,
                "iccid": sub.iccid,
                "terminatedAt": now.isoformat(),
            },
        )

        await self._session.commit()
        log.info("subscription.terminated", subscription_id=sub_id)
        return await self._repo.get(sub_id)

    async def _transition(
        self, sub: Subscription, trigger: str, *, reason: str = ""
    ) -> None:
        if not is_valid_transition(sub.state, trigger):
            raise PolicyViolation(
                rule="subscription.transition.invalid",
                message=f"Cannot trigger '{trigger}' from state '{sub.state}'",
                context={"state": sub.state, "trigger": trigger},
            )
        from_state = sub.state
        to_state = get_next_state(sub.state, trigger)
        sub.state = to_state
        sub.state_reason = reason

        entry = SubscriptionStateHistory(
            subscription_id=sub.id,
            from_state=from_state,
            to_state=to_state,
            changed_by="system",
            reason=reason,
        )
        await self._repo.add_state_history(entry)
