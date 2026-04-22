"""LLM REPL session — conversation state + single-shot ``ask`` helper.

Two entry points:

- ``ask_once(text, *, allow_destructive=False)`` — one-turn question/answer.
  Used by ``bss ask '…'``. No history across calls.

- ``Session(allow_destructive=...)`` — stateful multi-turn REPL object.
  Tracks the running ``messages`` list so the model sees prior turns. Used by
  the ``bss`` REPL entrypoint.

Both set ``use_llm_context()`` before invoking the graph so every downstream
bss-clients call carries ``X-BSS-Channel: llm`` + the model-derived actor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bss_telemetry import semconv, tracer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .context import use_llm_context
from .graph import build_graph


def _last_ai_text(messages: list[BaseMessage]) -> str:
    """Return the text of the final ``AIMessage`` in the turn, or empty."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            # some providers return list[{"type": "text", "text": ...}]
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
    return ""


@dataclass
class Session:
    """Multi-turn REPL session.

    The compiled graph is cached on the instance so we don't rebuild the
    tool list for every turn. Destructive gating is fixed at construction —
    toggling mid-session would be confusing, re-open the session instead.
    """

    allow_destructive: bool = False
    temperature: float = 0.0
    history: list[BaseMessage] = field(default_factory=list)
    _graph: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._graph = build_graph(
            allow_destructive=self.allow_destructive,
            temperature=self.temperature,
        )

    async def ask(self, text: str) -> str:
        """Send one user turn. Returns the assistant's reply text.

        Tool observations stay inside the LangGraph state — the user sees
        only the final natural-language answer. Full traces are available
        via ``self.history`` for debugging.
        """
        with tracer("bss-orchestrator").start_as_current_span("bss.ask") as span:
            span.set_attribute(semconv.BSS_CHANNEL, "llm")
            span.set_attribute("bss.ask.turn", len(self.history) // 2 + 1)
            use_llm_context()
            self.history.append(HumanMessage(content=text))
            state = await self._graph.ainvoke({"messages": self.history})
            self.history = list(state["messages"])
            return _last_ai_text(self.history)

    def reset(self) -> None:
        """Clear conversation history — next ``ask`` starts fresh."""
        self.history = []


async def ask_once(text: str, *, allow_destructive: bool = False) -> str:
    """Run a single question through a fresh graph — no session state kept.

    Equivalent to ``Session(...).ask(text)`` but skips the dataclass.
    """
    with tracer("bss-orchestrator").start_as_current_span("bss.ask") as span:
        span.set_attribute(semconv.BSS_CHANNEL, "llm")
        span.set_attribute("bss.ask.allow_destructive", allow_destructive)
        use_llm_context()
        graph = build_graph(allow_destructive=allow_destructive)
        state = await graph.ainvoke({"messages": [HumanMessage(content=text)]})
        return _last_ai_text(state["messages"])
