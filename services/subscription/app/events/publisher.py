"""Domain event publisher.

Writes to audit.domain_event in the same transaction as the domain write.
RabbitMQ publish is best-effort after persist (simplified outbox).
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import aio_pika
import structlog
from bss_clock import now as clock_now
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_context
from bss_models.audit import DomainEvent

log = structlog.get_logger()


async def publish(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict | None = None,
    exchange: aio_pika.abc.AbstractExchange | None = None,
) -> None:
    ctx = auth_context.current()
    event = DomainEvent(
        event_id=uuid4(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        occurred_at=clock_now(),
        actor=ctx.actor,
        channel=ctx.channel,
        tenant_id=ctx.tenant,
        payload=payload or {},
        schema_version=1,
        published_to_mq=False,
    )
    session.add(event)
    log.info(
        "event.published",
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )

    if exchange:
        try:
            msg = aio_pika.Message(
                body=json.dumps(payload or {}).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await exchange.publish(msg, routing_key=event_type)
            event.published_to_mq = True
        except Exception:
            log.warning("mq.publish.failed", event_type=event_type)
