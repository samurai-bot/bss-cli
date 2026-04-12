"""LLM-mode step executor.

Task #4 scope ships a stub that raises a clear error when an ``ask:``
step runs. Task #6 replaces this with a real LangGraph invocation that:

* opens an ``llm`` channel context (``use_llm_context``),
* runs the orchestrator supervisor graph with the interpolated prompt,
* captures the tool-call trace + final assistant message,
* returns a ``LLMStepOutcome`` the runner feeds into ``expect_*`` checks.

Keeping the stub separate from ``runner.py`` means the import graph for
the deterministic path never has to touch OpenRouter / LangGraph — that
keeps the ``--no-llm`` path honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import ScenarioContext
from .schema import AskStep


class LLMDisabled(RuntimeError):
    """Raised when an ``ask:`` step runs with ``--no-llm`` or before task #6."""


@dataclass
class LLMStepOutcome:
    """Everything an ``ask:`` step produces that expectations evaluate against."""

    final_message: str = ""
    tools_called: list[str] = field(default_factory=list)
    events_emitted: list[str] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    final_state_probe: dict[str, Any] = field(default_factory=dict)


async def execute_ask_step(
    step: AskStep,
    context: ScenarioContext,
    *,
    allow_llm: bool,
) -> LLMStepOutcome:
    """Run an ``ask:`` step and return the outcome.

    Raises ``LLMDisabled`` when ``allow_llm`` is False (``--no-llm`` flag)
    or in Task-#4 scope where the real executor is not yet wired.
    """
    if not allow_llm:
        raise LLMDisabled(
            f"ask: step {step.name!r} cannot run with --no-llm. "
            "Re-run without --no-llm or convert to an action: step."
        )
    # Task #4 placeholder — task #6 wires the LangGraph orchestrator here.
    raise LLMDisabled(
        f"ask: step {step.name!r}: LLM executor lands in Phase 10 task #6. "
        "Deterministic scenarios (action: / assert: only) work today."
    )
