"""Self-serve specific agent-render helpers.

The generic event projection + HTML rendering moved to
``bss_portal_ui.agent_log`` (extracted in v0.5 so the CSR portal
can reuse it). Re-export for backwards compatibility within
the self-serve package, and keep the self-serve-only ID harvester
here — the CUST-/ORD-/SUB-/LPA regexes only matter to the signup
flow that needs to redirect on completion.
"""

from __future__ import annotations

import re

# Re-exports — same import surface as v0.4.
from bss_portal_ui.agent_log import (  # noqa: F401
    RenderedEvent,
    project,
    render_html,
)

_CUST_RE = re.compile(r"CUST-[a-f0-9]+", re.IGNORECASE)
_ORD_RE = re.compile(r"ORD-\d+")
_SUB_RE = re.compile(r"SUB-\d+")
_LPA_RE = re.compile(r"LPA:[^ \"'\n]+")


def harvest_ids(result_text: str) -> dict[str, str]:
    """Return whichever signup-flow IDs appear in a tool result."""
    found: dict[str, str] = {}
    if m := _CUST_RE.search(result_text):
        found["customer_id"] = m.group(0)
    if m := _ORD_RE.search(result_text):
        found["order_id"] = m.group(0)
    if m := _SUB_RE.search(result_text):
        found["subscription_id"] = m.group(0)
    if m := _LPA_RE.search(result_text):
        found["activation_code"] = m.group(0)
    return found
