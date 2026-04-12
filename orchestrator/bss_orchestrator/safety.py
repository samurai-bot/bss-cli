"""Destructive-operation gating for LLM tool calls.

Policy: some tools can't be undone with a follow-up call (terminate a
subscription, remove a payment method, cancel an order). If the human hasn't
explicitly passed ``--allow-destructive``, these tools return a *structured*
error rather than executing:

    {"error": "DESTRUCTIVE_OPERATION_BLOCKED", "tool": "...", "message": "..."}

The LangGraph supervisor sees this structured error as the tool result and
either aborts cleanly or asks the user to re-run with the flag. Same pattern
as ``PolicyViolationFromServer`` — structured error, never a stack trace.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

# Every destructive tool in the registry. Matches the dotted name the LLM sees
# (``<domain>.<action>``), NOT the Python function name — LangGraph tools are
# registered with the dotted name via ``@tool(name=...)``.
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "customer.close",
        "customer.remove_contact_medium",
        "case.close",
        "ticket.cancel",
        "payment.remove_method",
        "order.cancel",
        "subscription.terminate",
        "provisioning.set_fault_injection",
        "admin.reset_operational_data",
        "admin.force_state",
    }
)


def is_destructive(tool_name: str) -> bool:
    """True if ``tool_name`` (dotted, e.g. ``subscription.terminate``) is gated."""
    return tool_name in DESTRUCTIVE_TOOLS


def wrap_destructive(
    tool_fn: Callable[..., Awaitable[Any]],
    *,
    tool_name: str,
    allow_destructive: bool,
) -> Callable[..., Awaitable[Any]]:
    """Return a coroutine wrapper that short-circuits if the tool is destructive
    and the CLI flag hasn't been set.

    Non-destructive tools are returned unchanged — no overhead.
    """
    if not is_destructive(tool_name):
        return tool_fn

    @functools.wraps(tool_fn)
    async def _gated(**kwargs: Any) -> Any:
        if not allow_destructive:
            return {
                "error": "DESTRUCTIVE_OPERATION_BLOCKED",
                "tool": tool_name,
                "message": (
                    f"Tool {tool_name!r} is destructive and requires "
                    "--allow-destructive. Ask the user to confirm and re-run "
                    "with this flag if they truly intend this operation."
                ),
            }
        return await tool_fn(**kwargs)

    return _gated
