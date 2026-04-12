"""Usage / mediation tools — TMF635 online mediation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..clients import get_clients
from ..types import IsoDatetime, Msisdn, SubscriptionId, UsageEventType, UsageUnit
from ._registry import register


@register("usage.simulate")
async def usage_simulate(
    msisdn: Msisdn,
    event_type: UsageEventType,
    quantity: int,
    unit: UsageUnit,
    event_time: IsoDatetime | None = None,
) -> dict[str, Any]:
    """Submit a single usage event to mediation. Primary way for the LLM /
    scenario runner to inject data/voice/SMS usage. Mediation decrements the
    matching subscription balance synchronously and may block the
    subscription if a bundle hits zero.

    Args:
        msisdn: 8-digit mobile number of the consuming subscription.
        event_type: One of ``data``, ``voice_minutes``, ``sms``.
        quantity: Integer amount in ``unit``.
        unit: One of ``mb``, ``gb``, ``minutes``, ``count``.
        event_time: Optional ISO-8601 timestamp. Defaults to ``now`` (UTC).

    Returns:
        Usage dict ``{id, msisdn, subscriptionId, processed, processingError?}``.
        If ``processed=False``, check ``processingError`` for the rejection reason.

    Raises:
        PolicyViolationFromServer: various; the usual recoveries are to check
        subscription state and add VAS if exhausted.
    """
    now = event_time or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return await get_clients().mediation.submit_usage(
        msisdn=msisdn,
        event_type=event_type,
        event_time=now,
        quantity=quantity,
        unit=unit,
        source="llm",
    )


@register("usage.history")
async def usage_history(
    subscription_id: SubscriptionId | None = None,
    msisdn: Msisdn | None = None,
    event_type: UsageEventType | None = None,
    since: IsoDatetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read recent usage events, optionally filtered.

    Args:
        subscription_id: Filter by subscription.
        msisdn: Filter by MSISDN.
        event_type: Filter by event type.
        since: Only events at or after this ISO-8601 timestamp.
        limit: Max rows (default 100, server cap 1000).

    Returns:
        List of usage dicts, newest first.

    Raises:
        (none expected — read tool)
    """
    return await get_clients().mediation.list_usage(
        subscription_id=subscription_id,
        msisdn=msisdn,
        event_type=event_type,
        since=since,
        limit=limit,
    )
