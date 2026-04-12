"""RabbitMQ consumer for SOM — order.in_progress + provisioning task events."""

import json

import aio_pika
import structlog

from app.repositories.service_order_repo import ServiceOrderRepository
from app.repositories.service_repo import ServiceRepository

log = structlog.get_logger()


async def setup_consumer(app) -> None:
    """Set up MQ consumers in lifespan."""
    settings = app.state.settings
    if not settings.mq_url:
        log.warning("mq.not_configured")
        return

    connection = await aio_pika.connect_robust(settings.mq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=5)
    exchange = await channel.declare_exchange(
        "bss.events", aio_pika.ExchangeType.TOPIC, durable=True,
    )

    app.state.mq_connection = connection
    app.state.mq_exchange = exchange

    # ── Queue: order.in_progress ─────────────────────────────────────
    q_order = await channel.declare_queue("som.order.in_progress", durable=True)
    await q_order.bind(exchange, "order.in_progress")

    async def on_order_in_progress(message: aio_pika.abc.AbstractIncomingMessage):
        async with message.process():
            body = json.loads(message.body)
            log.info(
                "mq.order.in_progress.received",
                commercial_order_id=body.get("commercialOrderId"),
            )
            async with app.state.session_factory() as session:
                from app.services.som_service import SOMService

                so_repo = ServiceOrderRepository(session)
                svc_repo = ServiceRepository(session)
                svc = SOMService(
                    session=session,
                    so_repo=so_repo,
                    svc_repo=svc_repo,
                    inventory_client=app.state.inventory_client,
                    exchange=exchange,
                )
                await svc.decompose(
                    commercial_order_id=body["commercialOrderId"],
                    customer_id=body["customerId"],
                    offering_id=body["offeringId"],
                    msisdn_preference=body.get("msisdnPreference"),
                    payment_method_id=body["paymentMethodId"],
                )
                await session.commit()

    await q_order.consume(on_order_in_progress)
    log.info("mq.consumer.started", queue="som.order.in_progress")

    # ── Queue: provisioning.task.completed ────────────────────────────
    q_completed = await channel.declare_queue("som.provisioning.task.completed", durable=True)
    await q_completed.bind(exchange, "provisioning.task.completed")

    async def on_task_completed(message: aio_pika.abc.AbstractIncomingMessage):
        async with message.process():
            body = json.loads(message.body)
            log.info(
                "mq.task.completed.received",
                service_id=body.get("serviceId"),
                task_type=body.get("taskType"),
            )
            async with app.state.session_factory() as session:
                from app.services.som_service import SOMService

                so_repo = ServiceOrderRepository(session)
                svc_repo = ServiceRepository(session)
                svc = SOMService(
                    session=session,
                    so_repo=so_repo,
                    svc_repo=svc_repo,
                    inventory_client=app.state.inventory_client,
                    exchange=exchange,
                )
                await svc.handle_task_completed(
                    service_id=body["serviceId"],
                    task_type=body["taskType"],
                    service_order_id=body["serviceOrderId"],
                    commercial_order_id=body.get("commercialOrderId", ""),
                )
                await session.commit()

    await q_completed.consume(on_task_completed)
    log.info("mq.consumer.started", queue="som.provisioning.task.completed")

    # ── Queue: provisioning.task.failed ───────────────────────────────
    q_failed = await channel.declare_queue("som.provisioning.task.failed", durable=True)
    await q_failed.bind(exchange, "provisioning.task.failed")

    async def on_task_failed(message: aio_pika.abc.AbstractIncomingMessage):
        async with message.process():
            body = json.loads(message.body)
            log.info(
                "mq.task.failed.received",
                service_id=body.get("serviceId"),
                task_type=body.get("taskType"),
            )
            async with app.state.session_factory() as session:
                from app.services.som_service import SOMService

                so_repo = ServiceOrderRepository(session)
                svc_repo = ServiceRepository(session)
                svc = SOMService(
                    session=session,
                    so_repo=so_repo,
                    svc_repo=svc_repo,
                    inventory_client=app.state.inventory_client,
                    exchange=exchange,
                )
                await svc.handle_task_failed(
                    service_id=body["serviceId"],
                    task_type=body["taskType"],
                    service_order_id=body["serviceOrderId"],
                    commercial_order_id=body.get("commercialOrderId", ""),
                    permanent=body.get("permanent", True),
                )
                await session.commit()

    await q_failed.consume(on_task_failed)
    log.info("mq.consumer.started", queue="som.provisioning.task.failed")

    # ── Queue: provisioning.task.stuck ────────────────────────────────
    q_stuck = await channel.declare_queue("som.provisioning.task.stuck", durable=True)
    await q_stuck.bind(exchange, "provisioning.task.stuck")

    async def on_task_stuck(message: aio_pika.abc.AbstractIncomingMessage):
        async with message.process():
            body = json.loads(message.body)
            log.info(
                "mq.task.stuck.received",
                service_id=body.get("serviceId"),
                task_type=body.get("taskType"),
            )
            async with app.state.session_factory() as session:
                from app.services.som_service import SOMService

                so_repo = ServiceOrderRepository(session)
                svc_repo = ServiceRepository(session)
                svc = SOMService(
                    session=session,
                    so_repo=so_repo,
                    svc_repo=svc_repo,
                    inventory_client=app.state.inventory_client,
                    exchange=exchange,
                )
                await svc.handle_task_stuck(
                    service_id=body["serviceId"],
                    task_type=body["taskType"],
                    service_order_id=body["serviceOrderId"],
                )
                await session.commit()

    await q_stuck.consume(on_task_stuck)
    log.info("mq.consumer.started", queue="som.provisioning.task.stuck")
