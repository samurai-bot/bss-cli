"""Ops / observability tools — clock, trace, events, agents.

Clock/trace/events are thin scaffolding in v0.1. A dedicated scenario clock
service and the event-bus query surface arrive in Phase 11; until then the
tools return structured ``NOT_IMPLEMENTED`` payloads so the LLM can explain
the gap to the user rather than crashing mid-turn. ``clock.now`` and the
``agents.*`` tools are live.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bss_clock import now as clock_now

from ..clients import get_clients
from ..types import (
    AgentState,
    AggregateId,
    AggregateType,
    IsoDatetime,
    OrderId,
    SubscriptionId,
)
from ._registry import register

_CLOCK_NOT_IMPLEMENTED = {
    "error": "NOT_IMPLEMENTED",
    "message": (
        "Virtual clock control ships in Phase 11 (scenario runner). In v0.1 "
        "the system clock is authoritative — use clock.now to read it."
    ),
}

_TRACE_NOT_IMPLEMENTED = {
    "error": "NOT_IMPLEMENTED",
    "message": (
        "Cross-service trace aggregation ships in Phase 11. Until then, use "
        "the per-aggregate reads (order.get, subscription.get, etc.) and the "
        "audit.domain_event table directly."
    ),
}

_EVENTS_NOT_IMPLEMENTED = {
    "error": "NOT_IMPLEMENTED",
    "message": (
        "Event-bus query tools ship in Phase 11. Events are already persisted "
        "to audit.domain_event in every service schema; query them via SQL for now."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Clock
# ─────────────────────────────────────────────────────────────────────────────


@register("clock.now")
async def clock_now() -> dict[str, Any]:
    """Return the current wall-clock time as ISO-8601 UTC. Use this whenever
    a tool needs a ``since`` / ``event_time`` value — do NOT fabricate timestamps.

    Args:
        (none)

    Returns:
        ``{now: IsoDatetime, source: "system"}``. In Phase 11 ``source`` will
        become ``"scenario"`` when a virtual clock is active.

    Raises:
        (none)
    """
    now = clock_now().replace(microsecond=0).isoformat()
    return {"now": now, "source": "system"}


@register("clock.advance")
async def clock_advance(duration: str) -> dict[str, Any]:
    """Advance the scenario clock by a duration. NOT IMPLEMENTED in v0.1.

    Args:
        duration: Duration string, e.g. ``"1h"``, ``"30d"``.

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {**_CLOCK_NOT_IMPLEMENTED, "duration": duration}


@register("clock.freeze")
async def clock_freeze(at: IsoDatetime | None = None) -> dict[str, Any]:
    """Freeze the scenario clock. NOT IMPLEMENTED in v0.1.

    Args:
        at: Optional ISO-8601 instant to freeze at; defaults to ``now``.

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {**_CLOCK_NOT_IMPLEMENTED, "requestedAt": at}


@register("clock.unfreeze")
async def clock_unfreeze() -> dict[str, Any]:
    """Resume the scenario clock. NOT IMPLEMENTED in v0.1.

    Args:
        (none)

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return dict(_CLOCK_NOT_IMPLEMENTED)


# ─────────────────────────────────────────────────────────────────────────────
# Trace / events (Phase 11 stubs)
# ─────────────────────────────────────────────────────────────────────────────


@register("trace.get")
async def trace_get(
    aggregate_type: AggregateType,
    aggregate_id: AggregateId,
) -> dict[str, Any]:
    """Return the full event trace for any aggregate. NOT IMPLEMENTED in v0.1.

    Args:
        aggregate_type: Aggregate kind, e.g. ``"order"`` or ``"subscription"``.
        aggregate_id: ID of the aggregate, prefix must match its kind.

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {
        **_TRACE_NOT_IMPLEMENTED,
        "aggregateType": aggregate_type,
        "aggregateId": aggregate_id,
    }


@register("trace.for_order")
async def trace_for_order(order_id: OrderId) -> dict[str, Any]:
    """Return the order → SO → services → provisioning trace. NOT IMPLEMENTED in v0.1.

    Args:
        order_id: Commercial Order ID in ORD-NNN format.

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {**_TRACE_NOT_IMPLEMENTED, "orderId": order_id}


@register("trace.for_subscription")
async def trace_for_subscription(subscription_id: SubscriptionId) -> dict[str, Any]:
    """Return the lifecycle trace for a subscription. NOT IMPLEMENTED in v0.1.

    Args:
        subscription_id: Subscription ID in SUB-NNN format.

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {**_TRACE_NOT_IMPLEMENTED, "subscriptionId": subscription_id}


@register("events.list")
async def events_list(
    aggregate_type: AggregateType | None = None,
    aggregate_id: AggregateId | None = None,
    since: IsoDatetime | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List recent domain events. NOT IMPLEMENTED in v0.1.

    Args:
        aggregate_type: Optional filter by aggregate kind.
        aggregate_id: Optional filter by aggregate ID.
        since: Optional ISO-8601 lower bound.
        limit: Max rows (default 50).

    Returns:
        v0.1: structured ``NOT_IMPLEMENTED`` payload.

    Raises:
        (none in v0.1)
    """
    return {
        **_EVENTS_NOT_IMPLEMENTED,
        "aggregateType": aggregate_type,
        "aggregateId": aggregate_id,
        "since": since,
        "limit": limit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agents (CRM)
# ─────────────────────────────────────────────────────────────────────────────


@register("agents.list")
async def agents_list(state: AgentState | None = None) -> list[dict[str, Any]]:
    """List CSR/support agents. Used before case/ticket assignment to pick a
    valid assignee.

    Args:
        state: Optional filter — typically ``"active"``.

    Returns:
        List of agent dicts ``{id, name, email, state, roles}``.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().crm.list_agents(state=state)


