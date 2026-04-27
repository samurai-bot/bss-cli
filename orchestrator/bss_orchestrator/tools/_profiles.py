"""Tool profiles — per-surface curated subsets of TOOL_REGISTRY (v0.12).

Default behaviour for ``astream_once`` (no profile specified) remains
full-tool access — CLI, scenarios, and the v0.5 CSR console keep
their current capability. Only the chat surface invokes with
``tool_filter="customer_self_serve"`` so the LLM can act only on the
logged-in customer.

The registry is curated, not generated. Adding a tool is a security
review: each entry widens the chat's autonomous reach, so each entry
must be ownership-bound (either via a ``*.mine`` wrapper, or because
the tool is a public catalog read with no customer-bound output).

Greppable: every name in this module's value sets must resolve in
``TOOL_REGISTRY`` at startup. ``validate_profiles()`` enforces this
plus the "no customer_id parameter" rule for ``*.mine`` wrappers.
"""

from __future__ import annotations

import inspect

from ._registry import TOOL_REGISTRY

# Parameter names a *.mine wrapper must NOT accept. The wrapper binds
# customer_id from auth_context.current().actor; accepting it as a
# parameter would let a prompt-injected LLM target another customer
# even though every server-side policy still blocks the cross-customer
# attempt. The seam exists so that prompt-injection containment does
# not depend on the LLM behaving.
FORBIDDEN_MINE_PARAMETERS: frozenset[str] = frozenset(
    {
        "customer_id",
        "customer_email",
        "msisdn",
    }
)


TOOL_PROFILES: dict[str, set[str]] = {
    # v0.12 — the chat surface profile. Each tool is either a
    # public catalog read or a ``*.mine``/``*_for_me`` wrapper that
    # binds customer_id from auth_context.
    #
    # PR2 shipped the read-only tools.
    # PR3 added the four write *.mine wrappers.
    # PR6 will add case.open_for_me.
    "customer_self_serve": {
        # public catalog reads — no customer-bound output, safe in any
        # session
        "catalog.list_vas",
        "catalog.list_active_offerings",
        "catalog.get_offering",
        # read .mine wrappers (PR2)
        "subscription.list_mine",
        "subscription.get_mine",
        "subscription.get_balance_mine",
        "subscription.get_lpa_mine",
        "usage.history_mine",
        "customer.get_mine",
        "payment.method_list_mine",
        "payment.charge_history_mine",
        # write .mine wrappers (PR3)
        "vas.purchase_for_me",
        "subscription.schedule_plan_change_mine",
        "subscription.cancel_pending_plan_change_mine",
        "subscription.terminate_mine",
        # case open — added in PR6:
        # "case.open_for_me",
    },
}


def get_profile(name: str) -> set[str]:
    """Return the tool name set for ``name``. KeyError if unknown."""
    return TOOL_PROFILES[name]


def is_mine_tool(tool_name: str) -> bool:
    """True for the ``*.mine`` and ``*_for_me`` wrapper names."""
    return tool_name.endswith(".mine") or tool_name.endswith("_mine") or tool_name.endswith("_for_me")


def validate_profiles() -> None:
    """Check every profile + wrapper invariant. Raise on violation.

    Called at orchestrator import time so deploys fail fast rather
    than at the first chat turn:

    1. Every name listed in any profile is registered in TOOL_REGISTRY.
    2. Every ``*.mine`` / ``*_for_me`` tool's signature does not accept
       a forbidden owner-bound parameter.
    3. Every tool in the ``customer_self_serve`` profile has an entry
       in ``OWNERSHIP_PATHS`` (use ``[]`` for tools whose response
       carries no customer-bound fields by contract).

    Raises:
        RuntimeError: profile drift (missing tool), signature
            violation (forbidden parameter), or OWNERSHIP_PATHS
            coverage gap.
    """
    for profile_name, tool_names in TOOL_PROFILES.items():
        for name in sorted(tool_names):
            if name not in TOOL_REGISTRY:
                raise RuntimeError(
                    f"Profile {profile_name!r} lists unregistered tool "
                    f"{name!r}. Either add the tool or remove from "
                    f"_profiles.py."
                )

    # *.mine signature inspection — applies across every registered
    # mine tool, not just those in the customer profile. A mine tool
    # that grew a customer_id parameter "for refactoring convenience"
    # is the worst regression we want to catch at deploy time.
    for name, fn in TOOL_REGISTRY.items():
        if not is_mine_tool(name):
            continue
        sig = inspect.signature(fn)
        forbidden = sorted(
            p for p in sig.parameters if p in FORBIDDEN_MINE_PARAMETERS
        )
        if forbidden:
            raise RuntimeError(
                f"Tool {name!r} accepts forbidden parameter(s) "
                f"{forbidden!r}. *.mine wrappers must bind customer_id "
                f"from auth_context.current().actor — never from a "
                f"caller-supplied parameter."
            )

    # v0.12 PR4 — every customer_self_serve tool has an OWNERSHIP_PATHS
    # entry. Imported lazily so this module stays decoupled from
    # ownership.py (which imports nothing from here).
    from ..ownership import validate_ownership_paths_cover_profile

    validate_ownership_paths_cover_profile(TOOL_PROFILES["customer_self_serve"])
