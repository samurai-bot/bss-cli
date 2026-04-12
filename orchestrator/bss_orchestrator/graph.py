"""LangGraph supervisor graph — binds TOOL_REGISTRY + safety gating + LLM.

Call ``build_graph(allow_destructive=...)`` to get a compiled agent. The
returned object has the ``ainvoke``/``astream`` surface from
``langgraph.prebuilt.create_react_agent``.

Design notes:
- Tools stay dumb. All retry/planning behaviour lives in the ReAct loop.
- Each Python async function in ``TOOL_REGISTRY`` is wrapped by
  ``wrap_destructive`` then registered as a ``StructuredTool`` with the
  dotted name the LLM sees (``subscription.purchase_vas``).
- Descriptions come straight from the function docstring — the semantic
  contract the tests enforce.
- Arg schemas are inferred by LangChain from the coroutine signature, so the
  ``Annotated[str, "format hint"]`` metadata in ``types.py`` flows into the
  JSON Schema the model sees. That is the whole point of the semantic layer.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from .llm import build_chat_model
from .prompts import SYSTEM_PROMPT
from .safety import wrap_destructive
from .tools import TOOL_REGISTRY


def _as_structured_tool(name: str, fn: Any, *, allow_destructive: bool) -> StructuredTool:
    """Wrap a registered async tool as a LangChain ``StructuredTool``."""
    gated = wrap_destructive(fn, tool_name=name, allow_destructive=allow_destructive)
    description = (fn.__doc__ or "").strip() or f"BSS tool {name}."
    return StructuredTool.from_function(
        coroutine=gated,
        name=name,
        description=description,
    )


def build_tools(*, allow_destructive: bool = False) -> list[StructuredTool]:
    """Return every registered tool, safety-wrapped, as a StructuredTool list."""
    return [
        _as_structured_tool(name, fn, allow_destructive=allow_destructive)
        for name, fn in sorted(TOOL_REGISTRY.items())
    ]


def build_graph(*, allow_destructive: bool = False, temperature: float = 0.0) -> Any:
    """Compile a ReAct agent over the full BSS tool surface.

    Args:
        allow_destructive: If ``False`` (default) every destructive tool call
            short-circuits with a structured ``DESTRUCTIVE_OPERATION_BLOCKED``
            result and the LLM sees that and explains the situation to the
            user. Set to ``True`` only when the human has passed
            ``--allow-destructive``.
        temperature: LLM sampling temperature. Default ``0.0``.

    Returns:
        A compiled LangGraph runnable. Invoke with
        ``{"messages": [("user", text)]}`` → receive updated messages.
    """
    llm = build_chat_model(temperature=temperature)
    tools = build_tools(allow_destructive=allow_destructive)
    return create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
