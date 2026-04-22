"""Order orchestration service — calls policies, not repositories directly."""

from datetime import datetime, timezone

import structlog
from bss_clock import now as clock_now
from bss_telemetry import semconv, tracer
from sqlalchemy.ext.asyncio import AsyncSession

from bss_models.order_mgmt import OrderItem, ProductOrder

from app.events.publisher import publish
from app.policies.base import PolicyViolation
from app.policies.order import (
    check_cancel_allowed_after_som,
    check_customer_exists,
    check_customer_has_payment_method,
    check_offering_exists,
    check_order_transition,
)
from app.repositories.order_repo import OrderRepository

log = structlog.get_logger()


class OrderService:
    def __init__(
        self,
        session: AsyncSession,
        repo: OrderRepository,
        crm_client,
        catalog_client,
        payment_client,
        som_client,
        subscription_client,
        exchange,
    ):
        self._session = session
        self._repo = repo
        self._crm = crm_client
        self._catalog = catalog_client
        self._payment = payment_client
        self._som = som_client
        self._subscription = subscription_client
        self._exchange = exchange

    async def create_order(
        self,
        *,
        customer_id: str,
        offering_id: str,
        msisdn_preference: str | None = None,
        notes: str | None = None,
    ) -> ProductOrder:
        """Create a new order (acknowledged)."""
        await check_customer_exists(customer_id, self._crm)
        await check_offering_exists(offering_id, self._catalog)
        await check_customer_has_payment_method(customer_id, self._payment)

        order_id = await self._repo.next_order_id()
        item_id = await self._repo.next_item_id()

        order = ProductOrder(
            id=order_id,
            customer_id=customer_id,
            state="acknowledged",
            order_date=clock_now(),
            msisdn_preference=msisdn_preference,
            notes=notes,
        )
        item = OrderItem(
            id=item_id,
            order_id=order_id,
            action="add",
            offering_id=offering_id,
            state="acknowledged",
        )
        self._session.add(item)
        await self._repo.create(order)

        await self._repo.add_state_history(order_id, None, "acknowledged", reason="order created")

        await publish(
            self._session,
            event_type="order.acknowledged",
            aggregate_type="ProductOrder",
            aggregate_id=order_id,
            payload={
                "commercialOrderId": order_id,
                "customerId": customer_id,
                "offeringId": offering_id,
            },
            exchange=self._exchange,
        )

        await self._session.commit()
        return await self._repo.get(order_id)

    async def submit_order(self, order_id: str) -> ProductOrder:
        """Submit an order (acknowledged -> in_progress), publish to MQ."""
        order = await self._repo.get(order_id)
        if not order:
            raise PolicyViolation(
                rule="order.not_found",
                message=f"Order {order_id} not found",
                context={"order_id": order_id},
            )

        check_order_transition(order.state, "in_progress")

        # Get payment method for event payload
        payment_methods = await self._payment.list_methods(order.customer_id)
        payment_method_id = payment_methods[0]["id"] if payment_methods else ""

        item = order.items[0] if order.items else None
        offering_id = item.offering_id if item else ""

        old_state = order.state
        order.state = "in_progress"
        await self._repo.add_state_history(order_id, old_state, "in_progress", reason="order submitted")
        await self._repo.update(order)

        # Publish order.in_progress event to MQ
        await publish(
            self._session,
            event_type="order.in_progress",
            aggregate_type="ProductOrder",
            aggregate_id=order_id,
            payload={
                "commercialOrderId": order_id,
                "customerId": order.customer_id,
                "offeringId": offering_id,
                "msisdnPreference": order.msisdn_preference,
                "paymentMethodId": payment_method_id,
            },
            exchange=self._exchange,
        )

        await self._session.commit()
        return await self._repo.get(order_id)

    async def cancel_order(self, order_id: str) -> ProductOrder:
        """Cancel an order — acknowledged always OK, in_progress only if SOM hasn't started."""
        order = await self._repo.get(order_id)
        if not order:
            raise PolicyViolation(
                rule="order.not_found",
                message=f"Order {order_id} not found",
                context={"order_id": order_id},
            )

        check_order_transition(order.state, "cancelled")

        if order.state == "in_progress":
            await check_cancel_allowed_after_som(order_id, self._som)

        old_state = order.state
        order.state = "cancelled"
        order.completed_date = clock_now()
        await self._repo.add_state_history(order_id, old_state, "cancelled", reason="cancelled by user")
        await self._repo.update(order)

        await publish(
            self._session,
            event_type="order.cancelled",
            aggregate_type="ProductOrder",
            aggregate_id=order_id,
            payload={
                "commercialOrderId": order_id,
                "customerId": order.customer_id,
            },
            exchange=self._exchange,
        )

        await self._session.commit()
        return await self._repo.get(order_id)

    async def handle_service_order_completed(
        self,
        *,
        commercial_order_id: str,
        customer_id: str,
        offering_id: str,
        msisdn: str,
        iccid: str,
        payment_method_id: str,
        cfs_service_id: str,
    ) -> None:
        """Called from MQ consumer when service_order.completed."""
        with tracer("bss-com").start_as_current_span(
            "com.order.complete_to_subscription"
        ) as span:
            span.set_attribute(semconv.BSS_ORDER_ID, commercial_order_id)
            span.set_attribute(semconv.BSS_CUSTOMER_ID, customer_id)
            span.set_attribute(semconv.BSS_OFFERING_ID, offering_id)

            order = await self._repo.get(commercial_order_id)
            if not order or order.state != "in_progress":
                log.warning(
                    "order.service_order_completed.skipped",
                    commercial_order_id=commercial_order_id,
                    reason="order not found or not in_progress",
                )
                return

            # Create subscription
            sub_result = await self._subscription.create(
                customer_id=customer_id,
                offering_id=offering_id,
                msisdn=msisdn,
                iccid=iccid,
                payment_method_id=payment_method_id,
            )
            if sub_result.get("id"):
                span.set_attribute(semconv.BSS_SUBSCRIPTION_ID, sub_result["id"])

            # Update order item
            if order.items:
                order.items[0].target_subscription_id = sub_result.get("id")
                order.items[0].state = "completed"

            check_order_transition(order.state, "completed")
            order.state = "completed"
            order.completed_date = clock_now()
            await self._repo.add_state_history(
                order.id, "in_progress", "completed", reason="service order completed"
            )

            await publish(
                self._session,
                event_type="order.completed",
                aggregate_type="ProductOrder",
                aggregate_id=order.id,
                payload={
                    "commercialOrderId": order.id,
                    "customerId": order.customer_id,
                    "subscriptionId": sub_result.get("id"),
                    "cfsServiceId": cfs_service_id,
                },
                exchange=self._exchange,
            )
            # NOTE: session.commit() is done by the consumer

    async def handle_service_order_failed(
        self,
        *,
        commercial_order_id: str,
        reason: str,
    ) -> None:
        """Called from MQ consumer when service_order.failed."""
        order = await self._repo.get(commercial_order_id)
        if not order or order.state != "in_progress":
            log.warning(
                "order.service_order_failed.skipped",
                commercial_order_id=commercial_order_id,
                reason="order not found or not in_progress",
            )
            return

        check_order_transition(order.state, "failed")
        order.state = "failed"
        order.completed_date = clock_now()
        if order.items:
            order.items[0].state = "failed"

        await self._repo.add_state_history(
            order.id, "in_progress", "failed", reason=reason
        )

        await publish(
            self._session,
            event_type="order.failed",
            aggregate_type="ProductOrder",
            aggregate_id=order.id,
            payload={
                "commercialOrderId": order.id,
                "customerId": order.customer_id,
                "reason": reason,
            },
            exchange=self._exchange,
        )
        # NOTE: session.commit() is done by the consumer

    async def get_order(self, order_id: str) -> ProductOrder | None:
        """Read-only: get a single order."""
        return await self._repo.get(order_id)

    async def list_orders_for_customer(self, customer_id: str) -> list[ProductOrder]:
        """Read-only: list orders for a customer."""
        return await self._repo.list_by_customer(customer_id)
