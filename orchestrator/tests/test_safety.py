"""Unit tests for destructive-operation gating."""

from __future__ import annotations

import pytest

from bss_orchestrator.safety import (
    DESTRUCTIVE_TOOLS,
    is_destructive,
    wrap_destructive,
)


def test_known_destructive_tools_flagged() -> None:
    for name in [
        "subscription.terminate",
        "order.cancel",
        "payment.remove_method",
        "case.close",
    ]:
        assert is_destructive(name), name


def test_readonly_tools_not_flagged() -> None:
    for name in ["customer.get", "subscription.get", "catalog.list_offerings"]:
        assert not is_destructive(name), name


@pytest.mark.asyncio
async def test_wrap_destructive_blocks_by_default() -> None:
    called = False

    async def terminate(**kwargs):
        nonlocal called
        called = True
        return {"id": kwargs["subscription_id"], "state": "terminated"}

    gated = wrap_destructive(
        terminate, tool_name="subscription.terminate", allow_destructive=False
    )
    result = await gated(subscription_id="SUB-007")
    assert result["error"] == "DESTRUCTIVE_OPERATION_BLOCKED"
    assert result["tool"] == "subscription.terminate"
    assert called is False  # underlying fn must not run


@pytest.mark.asyncio
async def test_wrap_destructive_runs_when_allowed() -> None:
    async def terminate(**kwargs):
        return {"id": kwargs["subscription_id"], "state": "terminated"}

    gated = wrap_destructive(
        terminate, tool_name="subscription.terminate", allow_destructive=True
    )
    result = await gated(subscription_id="SUB-007")
    assert result == {"id": "SUB-007", "state": "terminated"}


@pytest.mark.asyncio
async def test_wrap_destructive_returns_fn_unchanged_for_read_tools() -> None:
    async def get(**kwargs):
        return {"id": kwargs["customer_id"]}

    wrapped = wrap_destructive(
        get, tool_name="customer.get", allow_destructive=False
    )
    # Non-destructive: returned untouched (same object).
    assert wrapped is get


def test_destructive_set_matches_doctrine() -> None:
    # Sanity — the gated list must include the doctrine-enumerated destructive ops.
    required = {
        "subscription.terminate",
        "order.cancel",
        "payment.remove_method",
        "case.close",
        "ticket.cancel",
        "customer.close",
    }
    assert required.issubset(DESTRUCTIVE_TOOLS)
