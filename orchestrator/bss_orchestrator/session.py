"""LLM REPL session — conversation state + single-shot + streaming entry points.

Three entry points:

- ``ask_once(text, *, allow_destructive=False)`` — one-turn blocking call.
  Used by ``bss ask '…'``. No history.

- ``Session(allow_destructive=...)`` — stateful multi-turn REPL object.
  Tracks the running ``messages`` list so the model sees prior turns. Used
  by the ``bss`` REPL entrypoint.

- ``astream_once(text, *, allow_destructive=False, channel="llm")`` (v0.4+)
  — streaming variant of ask_once. Yields typed ``AgentEvent`` dataclasses
  as the graph produces them. Used by portals to render tool-call logs
  live via SSE. Same tool-chain as ask_once, same policy gating; just
  observable as it happens.

All three set the bss-clients context (channel header) before invoking the
graph so downstream service-to-service calls carry the right attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Union

from bss_telemetry import semconv, tracer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from .context import use_channel_context, use_llm_context
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


# ─────────────────────────────────────────────────────────────────────────────
# Streaming event types (v0.4 — portal agent log widget)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentEventPromptReceived:
    """Emitted once at the start of the stream with the caller's raw prompt."""

    prompt: str


@dataclass(frozen=True)
class AgentEventToolCallStarted:
    """The LLM decided to invoke a tool. Emitted before the tool runs."""

    name: str
    args: dict[str, Any]
    call_id: str


@dataclass(frozen=True)
class AgentEventToolCallCompleted:
    """The tool's result came back. ``result`` is a truncated string repr."""

    name: str
    call_id: str
    result: str
    is_error: bool = False


@dataclass(frozen=True)
class AgentEventFinalMessage:
    """Last AI message with no further tool calls — the end of the turn."""

    text: str


@dataclass(frozen=True)
class AgentEventError:
    """The graph or a tool raised an exception that escaped all handlers."""

    message: str


AgentEvent = Union[
    AgentEventPromptReceived,
    AgentEventToolCallStarted,
    AgentEventToolCallCompleted,
    AgentEventFinalMessage,
    AgentEventError,
]


_RESULT_TRUNCATE = 500


def _truncate(text: str, limit: int = _RESULT_TRUNCATE) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ─────────────────────────────────────────────────────────────────────────────
# Session + ask_once
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Session:
    """Multi-turn REPL session.

    The compiled graph is cached on the instance so we don't rebuild the
    tool list for every turn. Destructive gating is fixed at construction —
    toggling mid-session would be confusing, re-open the session instead.
    """

    allow_destructive: bool = False
    temperature: float = 0.0
    history: list[BaseMessage] = None  # type: ignore[assignment]
    _graph: Any = None

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []
        self._graph = build_graph(
            allow_destructive=self.allow_destructive,
            temperature=self.temperature,
        )

    async def ask(self, text: str) -> str:
        """Send one user turn. Returns the assistant's reply text."""
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
    """Run a single question through a fresh graph — no session state kept."""
    with tracer("bss-orchestrator").start_as_current_span("bss.ask") as span:
        span.set_attribute(semconv.BSS_CHANNEL, "llm")
        span.set_attribute("bss.ask.allow_destructive", allow_destructive)
        use_llm_context()
        graph = build_graph(allow_destructive=allow_destructive)
        state = await graph.ainvoke({"messages": [HumanMessage(content=text)]})
        return _last_ai_text(state["messages"])


# ─────────────────────────────────────────────────────────────────────────────
# astream_once — v0.4 streaming entry point
# ─────────────────────────────────────────────────────────────────────────────


async def astream_once(
    prompt: str,
    *,
    allow_destructive: bool = False,
    channel: str = "llm",
    actor: str | None = None,
) -> AsyncIterator[AgentEvent]:
    """Streaming variant of ``ask_once``. Yields ``AgentEvent`` as the graph runs.

    The ``channel`` parameter overrides the X-BSS-Channel header on every
    outbound bss-clients call so CRM's interaction log can attribute the
    resulting actions to the right surface (v0.4 portal uses
    ``channel="portal-self-serve"``; v0.5 CSR uses ``channel="portal-csr"``).

    The ``actor`` parameter (v0.5+) sets X-BSS-Actor on outbound calls.
    The CSR portal passes the operator's id (``actor=<operator_id>``)
    so the interaction log attributes actions to the human who asked
    rather than to ``llm-<model-slug>``. Per-model attribution still
    lives in ``audit.domain_event.actor``. Defaults to ``settings.llm_actor``
    when ``channel != "llm"`` and no actor is given (preserves v0.4 behaviour).

    Event sequence:
    1. One ``AgentEventPromptReceived`` at the start.
    2. ``AgentEventToolCallStarted`` + ``AgentEventToolCallCompleted`` pairs
       as the LLM chains tool calls.
    3. One ``AgentEventFinalMessage`` when the agent stops calling tools.
    4. If anything raises past the graph's own error wrapping, one
       ``AgentEventError`` and the stream terminates.

    Contract note: tool observations are already converted to structured
    strings inside the graph (the try/except in ``_as_structured_tool`` —
    see DECISIONS.md 2026-04-12 Phase 10). This function observes those
    results and surfaces them as events; it does not add its own retry or
    recovery.
    """
    with tracer("bss-orchestrator").start_as_current_span("bss.ask") as span:
        span.set_attribute(semconv.BSS_CHANNEL, channel)
        span.set_attribute("bss.ask.allow_destructive", allow_destructive)
        span.set_attribute("bss.ask.streaming", True)
        if actor:
            span.set_attribute("bss.actor", actor)

        if channel == "llm":
            use_llm_context()
        else:
            use_channel_context(channel=channel, actor=actor)

        yield AgentEventPromptReceived(prompt=prompt)

        graph = build_graph(allow_destructive=allow_destructive)
        seen_call_ids: set[str] = set()
        last_ai_text = ""

        try:
            async for update in graph.astream(
                {"messages": [HumanMessage(content=prompt)]},
                stream_mode="updates",
            ):
                # update shape: {node_name: {"messages": [new_messages...]}}
                for node_output in update.values():
                    messages = node_output.get("messages", []) if isinstance(node_output, dict) else []
                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            tool_calls = getattr(msg, "tool_calls", []) or []
                            for tc in tool_calls:
                                call_id = tc.get("id", "") or ""
                                if call_id in seen_call_ids:
                                    continue
                                seen_call_ids.add(call_id)
                                yield AgentEventToolCallStarted(
                                    name=tc.get("name", "") or "",
                                    args=tc.get("args", {}) or {},
                                    call_id=call_id,
                                )
                            # Track the latest textual AI message so we emit
                            # the right "final" text at the end. The final
                            # message is the AIMessage without tool_calls.
                            text = _ai_text(msg)
                            if text and not tool_calls:
                                last_ai_text = text
                        elif isinstance(msg, ToolMessage):
                            yield AgentEventToolCallCompleted(
                                name=msg.name or "",
                                call_id=msg.tool_call_id or "",
                                result=_truncate(str(msg.content) if msg.content is not None else ""),
                                is_error=getattr(msg, "status", None) == "error",
                            )
        except Exception as exc:  # noqa: BLE001
            yield AgentEventError(message=f"{type(exc).__name__}: {exc}")
            return

        yield AgentEventFinalMessage(text=last_ai_text)


def _ai_text(msg: AIMessage) -> str:
    """Extract the text of an AIMessage (handles string + list-of-parts content)."""
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    return ""
