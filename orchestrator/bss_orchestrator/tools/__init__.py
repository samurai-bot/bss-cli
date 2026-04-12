"""LLM tool surface — importing this package populates ``TOOL_REGISTRY``.

Every tool module decorates its functions with ``@register(...)`` at import
time. Importing the sub-modules below is therefore sufficient to assemble
the full registry; downstream code should consume ``TOOL_REGISTRY`` /
``get_tool`` / ``list_tools`` rather than reaching into modules directly.
"""

from __future__ import annotations

from . import (  # noqa: F401  (imports for side-effect: @register population)
    billing,
    case,
    catalog,
    customer,
    inventory,
    ops,
    order,
    payment,
    provisioning,
    som,
    subscription,
    ticket,
    usage,
)
from ._registry import TOOL_REGISTRY, get_tool, list_tools, register

__all__ = ["TOOL_REGISTRY", "get_tool", "list_tools", "register"]
