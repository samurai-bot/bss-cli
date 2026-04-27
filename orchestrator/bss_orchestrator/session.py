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

import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Union

from bss_clients import reset_service_identity_token, set_service_identity_token
from bss_telemetry import semconv, tracer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from . import auth_context
from .clients import get_clients
from .context import use_channel_context, use_llm_context
from .graph import build_graph
from .ownership import (
    AgentOwnershipViolation,
    assert_owned_output,
    record_violation,
)


def _resolve_token_for_service_identity(identity: str) -> str:
    """v0.9 — resolve a service_identity label to its env-loaded token.

    Mirrors the convention used by ``bss_middleware.api_token``:

    - ``"default"`` → ``BSS_API_TOKEN``
    - ``"<name>"`` → ``BSS_<NAME>_API_TOKEN`` (uppercased, underscored)

    Raises ``RuntimeError`` if the env var is unset. The orchestrator's
    own clients keep using ``BSS_API_TOKEN`` (via ``get_clients()``); the
    resolved token here is set into bss-clients' per-Context override
    so individual ``astream_once`` invocations can run "as another
    surface" for audit-attribution purposes (v0.11 portal chat).
    """
    if not identity:
        raise ValueError("service_identity must be a non-empty string")
    env_var = (
        "BSS_API_TOKEN" if identity == "default"
        else f"BSS_{identity.upper()}_API_TOKEN"
    )
    token = os.environ.get(env_var, "")
    if not token:
        raise RuntimeError(
            f"astream_once(service_identity={identity!r}): {env_var} is unset. "
            "The named token must be provisioned in the orchestrator's env "
            "for downstream calls to carry it. Generate via: openssl rand -hex 32"
        )
    return token


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
    """The tool's result came back.

    ``result`` is the truncated string repr — safe to flood into a
    log widget or SSE frame.

    ``result_full`` (v0.6+) is the untruncated string repr. Consumers
    that need to parse the JSON (e.g. the REPL's renderer-dispatch
    hook for ``*.get``-shaped tools) read this field. Defaults to
    the truncated value when full data wasn't captured (preserves
    backward compat for code that only used ``result``).
    """

    name: str
    call_id: str
    result: str
    is_error: bool = False
    result_full: str = ""


@dataclass(frozen=True)
class AgentEventFinalMessage:
    """Last AI message with no further tool calls — the end of the turn."""

    text: str


@dataclass(frozen=True)
class AgentEventError:
    """The graph or a tool raised an exception that escaped all handlers."""

    message: str


@dataclass(frozen=True)
class AgentEventTurnUsage:
    """v0.12 — token counts for the completed turn so the chat route
    can call ``chat_caps.record_chat_turn`` with the right numbers.

    Emitted once at stream end after ``AgentEventFinalMessage`` when
    the LLM's response surfaced ``usage_metadata``. ``model`` carries
    the model identifier used so the rate table looks up the right
    rates even if ``BSS_LLM_MODEL`` changes between turns.
    """

    prompt_tok: int
    completion_tok: int
    model: str


AgentEvent = Union[
    AgentEventPromptReceived,
    AgentEventToolCallStarted,
    AgentEventToolCallCompleted,
    AgentEventFinalMessage,
    AgentEventError,
    AgentEventTurnUsage,
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

    async def astream(self, text: str) -> AsyncIterator[AgentEvent]:
        """Streaming variant of :meth:`ask` — yields AgentEvents as the
        graph runs. Conversation history is updated as messages stream in.
        Used by the v0.6 REPL so tool-call observations can render live
        via the matching :mod:`bss_cli.renderers` alongside the model's
        text reply (rather than the prose-only view ``ask`` produced).
        """
        with tracer("bss-orchestrator").start_as_current_span("bss.ask") as span:
            span.set_attribute(semconv.BSS_CHANNEL, "llm")
            span.set_attribute("bss.ask.turn", len(self.history) // 2 + 1)
            span.set_attribute("bss.ask.streaming", True)
            use_llm_context()
            self.history.append(HumanMessage(content=text))
            yield AgentEventPromptReceived(prompt=text)

            seen_call_ids: set[str] = set()
            last_ai_text = ""

            try:
                async for update in self._graph.astream(
                    {"messages": self.history},
                    stream_mode="updates",
                ):
                    for node_output in update.values():
                        messages = node_output.get("messages", []) if isinstance(node_output, dict) else []
                        for msg in messages:
                            self.history.append(msg)
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
                                text_out = _ai_text(msg)
                                if text_out and not tool_calls:
                                    last_ai_text = text_out
                            elif isinstance(msg, ToolMessage):
                                full = str(msg.content) if msg.content is not None else ""
                                yield AgentEventToolCallCompleted(
                                    name=msg.name or "",
                                    call_id=msg.tool_call_id or "",
                                    result=_truncate(full),
                                    result_full=full,
                                    is_error=getattr(msg, "status", None) == "error",
                                )
            except Exception as exc:  # noqa: BLE001
                yield AgentEventError(message=f"{type(exc).__name__}: {exc}")
                return

            yield AgentEventFinalMessage(text=last_ai_text)

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
    service_identity: str | None = None,
    tool_filter: str | None = None,
    system_prompt: str | None = None,
    transcript: str = "",
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

    The ``tool_filter`` parameter (v0.12+) names a profile in
    ``TOOL_PROFILES`` (e.g. ``"customer_self_serve"``). When set, the
    LangGraph agent is constructed with the profile's tool subset
    instead of the full registry — the chat surface narrows the
    LLM-visible tools so an injected prompt cannot reach a tool the
    customer's own UI doesn't expose. ``None`` (default) keeps full
    access (CLI / scenario / CSR behaviour).

    The ``system_prompt`` parameter (v0.12+) overrides the canonical
    ``SYSTEM_PROMPT`` for this stream. v0.12 customer chat passes the
    customer-chat prompt with five-category escalation guidance.

    The ``service_identity`` parameter (v0.9+) overrides the X-BSS-API-Token
    on outbound bss-clients calls so audit rows attribute writes to the
    initiating surface (e.g. ``"portal_self_serve"`` when v0.11 portal chat
    routes a question through the orchestrator). The orchestrator's own
    clients are constructed with ``BSS_API_TOKEN``; this parameter
    populates a per-Context ``ContextVar`` that bss-clients reads on each
    request. The token is resolved by env-var convention (``"portal_self_serve"``
    → ``BSS_PORTAL_SELF_SERVE_API_TOKEN``); receiving services then resolve
    ``service_identity`` from token validation. Defaults to ``None`` —
    no override; callers using the orchestrator default identity get v0.4
    behaviour. v0.9 ships the parameter and propagation; the portal chat
    surface in v0.11 is the first caller.

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
        if service_identity:
            span.set_attribute("bss.service.identity", service_identity)

        if channel == "llm":
            use_llm_context()
        else:
            use_channel_context(channel=channel, actor=actor)

        # v0.9 — per-Context X-BSS-API-Token override. Resolves once
        # before the graph runs; reset on exit (in finally) so a stream
        # that raises still leaves the Context clean for whatever runs
        # next in the same task.
        identity_reset_token = None
        if service_identity:
            override_token = _resolve_token_for_service_identity(service_identity)
            identity_reset_token = set_service_identity_token(override_token)

        # v0.12 — bind the orchestrator-side auth_context for the
        # duration of this stream so the customer profile's *.mine
        # wrappers can read auth_context.current().actor. The
        # transcript carries the chat-session conversation history
        # for case.open_for_me's transcript-link when a customer
        # escalates. Reset in finally so a stream that raises still
        # leaves a clean Context for whatever runs next.
        auth_reset_token = None
        if actor:
            auth_reset_token = auth_context.set_actor(
                actor, transcript=transcript
            )

        try:
            yield AgentEventPromptReceived(prompt=prompt)

            graph = build_graph(
                allow_destructive=allow_destructive,
                tool_filter=tool_filter,
                system_prompt=system_prompt,
            )
            seen_call_ids: set[str] = set()
            last_ai_text = ""
            usage_total = {"input_tokens": 0, "output_tokens": 0, "model": ""}

            try:
                async for update in graph.astream(
                    {"messages": [HumanMessage(content=prompt)]},
                    stream_mode="updates",
                ):
                    # update shape: {node_name: {"messages": [new_messages...]}}
                    for node_output in update.values():
                        messages = (
                            node_output.get("messages", [])
                            if isinstance(node_output, dict) else []
                        )
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
                                # v0.12 — accumulate per-turn token
                                # counts so the chat route can record
                                # cost via chat_caps.record_chat_turn.
                                # langchain_openai surfaces usage_metadata
                                # on the final assistant message; some
                                # providers also emit on tool-call AI
                                # messages, so accumulate across all of
                                # them.
                                um = getattr(msg, "usage_metadata", None)
                                if um:
                                    usage_total["input_tokens"] += int(
                                        um.get("input_tokens") or 0
                                    )
                                    usage_total["output_tokens"] += int(
                                        um.get("output_tokens") or 0
                                    )
                                rm = getattr(msg, "response_metadata", None) or {}
                                model_name = rm.get("model_name") or rm.get("model")
                                if model_name:
                                    usage_total["model"] = model_name
                            elif isinstance(msg, ToolMessage):
                                full = (
                                    str(msg.content) if msg.content is not None else ""
                                )
                                is_error = (
                                    getattr(msg, "status", None) == "error"
                                )
                                yield AgentEventToolCallCompleted(
                                    name=msg.name or "",
                                    call_id=msg.tool_call_id or "",
                                    result=_truncate(full),
                                    result_full=full,
                                    is_error=is_error,
                                )
                                # v0.12 PR4 — output ownership trip-wire.
                                # Skips error-status results (they cannot
                                # carry customer-bound rows by definition)
                                # and runs only when an actor is bound
                                # (the chat surface) so non-chat callers
                                # (CLI / scenario / CSR) keep their
                                # full-surface behaviour.
                                if actor and not is_error and msg.name:
                                    try:
                                        assert_owned_output(
                                            tool_name=msg.name,
                                            result_json=full,
                                            actor=actor,
                                        )
                                    except AgentOwnershipViolation as v:
                                        # Best-effort audit trail
                                        # (record_violation has its own
                                        # try/except — never raises).
                                        # Then surface to the route
                                        # handler which renders the
                                        # generic user-facing message.
                                        await record_violation(
                                            crm_client=get_clients().crm,
                                            actor=actor,
                                            tool_name=v.tool_name,
                                            path=v.path,
                                            found=v.found,
                                            transcript_so_far=prompt,
                                        )
                                        yield AgentEventError(
                                            message=(
                                                f"AgentOwnershipViolation: "
                                                f"{v.tool_name}"
                                            )
                                        )
                                        return
            except Exception as exc:  # noqa: BLE001
                yield AgentEventError(message=f"{type(exc).__name__}: {exc}")
                return

            yield AgentEventFinalMessage(text=last_ai_text)
            # v0.12 — emit token totals so the chat route can call
            # chat_caps.record_chat_turn. Always emitted (even when
            # totals are 0) so downstream consumers can rely on the
            # event being present; the route ignores zero-token
            # turns. ``model`` falls back to the configured default
            # when the provider doesn't echo it.
            yield AgentEventTurnUsage(
                prompt_tok=usage_total["input_tokens"],
                completion_tok=usage_total["output_tokens"],
                model=usage_total["model"] or "",
            )
        finally:
            if identity_reset_token is not None:
                reset_service_identity_token(identity_reset_token)
            if auth_reset_token is not None:
                auth_context.reset_actor(auth_reset_token)


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
