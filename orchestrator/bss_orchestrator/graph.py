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

import functools
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from .llm import build_chat_model
from .prompts import SYSTEM_PROMPT
from .safety import wrap_destructive
from .tools import TOOL_REGISTRY

# Tools present in TOOL_REGISTRY (so scenarios can use them via ``action:``)
# but intentionally NOT exposed to the LLM. The LLM gets a model-visible
# subset — we pull out scenario-scaffolding tools that small models tend
# to misuse during troubleshooting (e.g. burning allowance to "test" a fix).
_LLM_HIDDEN_TOOLS: frozenset[str] = frozenset(
    {
        # Injects real usage events. Legit from a test harness or channel
        # layer; never from the copilot — read-only ``usage.history`` and
        # ``subscription.get`` are the right troubleshooting surfaces.
        "usage.simulate",
    }
)


def _tool_error_to_observation(exc: Exception) -> str:
    """Convert ANY exception from a tool call into an LLM-readable observation.

    PolicyViolationFromServer and ClientError carry structured ``rule`` /
    ``status_code`` + ``detail`` fields — expose them so the model can read
    the failure and recover (retry with corrections, ask the user, etc.)
    rather than watching the graph crash.
    """
    from bss_clients.errors import ClientError, PolicyViolationFromServer

    if isinstance(exc, PolicyViolationFromServer):
        return f'{{"error": "POLICY_VIOLATION", "rule": "{exc.rule}", "detail": {exc.detail!r}}}'
    if isinstance(exc, ClientError):
        return f'{{"error": "CLIENT_ERROR", "status": {exc.status_code}, "detail": {exc.detail!r}}}'
    return f'{{"error": "{type(exc).__name__}", "detail": "{exc}"}}'


def _as_structured_tool(name: str, fn: Any, *, allow_destructive: bool) -> StructuredTool:
    """Wrap a registered async tool as a LangChain ``StructuredTool``.

    We wrap the coroutine in a try/except that converts ANY exception to a
    string observation. LangChain's ``handle_tool_error`` only fires for
    ``ToolException``, and wrapping inside the coroutine means the graph
    never sees the exception at all — the tool simply returns an
    error-shaped string and the ReAct loop reads it as a normal observation.
    """
    gated = wrap_destructive(fn, tool_name=name, allow_destructive=allow_destructive)
    description = (fn.__doc__ or "").strip() or f"BSS tool {name}."

    # ``functools.wraps(fn)`` copies ``__wrapped__`` (among other dunders) so
    # ``inspect.signature`` — which LangChain uses to infer ``args_schema`` —
    # resolves back to ``fn``'s real signature with its ``Annotated[...]``
    # type hints. We need that so the JSON Schema the model sees matches
    # ``types.py``, not our generic ``**kwargs`` catch-all.
    @functools.wraps(fn)
    async def _safe(**kwargs: Any) -> Any:
        try:
            return await gated(**kwargs)
        except Exception as exc:
            return _tool_error_to_observation(exc)

    return StructuredTool.from_function(
        coroutine=_safe,
        name=name,
        description=description,
    )


def build_tools(*, allow_destructive: bool = False) -> list[StructuredTool]:
    """Return every LLM-visible tool, safety-wrapped, as a StructuredTool list."""
    return [
        _as_structured_tool(name, fn, allow_destructive=allow_destructive)
        for name, fn in sorted(TOOL_REGISTRY.items())
        if name not in _LLM_HIDDEN_TOOLS
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
