"""Real-network smoke test against OpenRouter.

Marked ``@pytest.mark.integration`` — excluded from ``make test`` by default.
Run explicitly with:

    uv run --package bss-orchestrator pytest orchestrator/tests/test_llm_integration.py -m integration

Requires ``BSS_LLM_API_KEY`` to be set (OpenRouter key). If absent, the test
is skipped rather than failed — local CI runs without credentials.

Scope: **prove the wiring, not the model.** We ask the LLM a trivial
question that exercises one tool call (``clock.now``), and assert:

1. The LLM actually produced an ``AIMessage`` (answer came back).
2. At least one tool invocation occurred.
3. No auth/config error was raised.

We intentionally do NOT assert the final text wording — small models
phrase things differently on every run.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from bss_orchestrator.config import settings
from bss_orchestrator.session import Session


pytestmark = pytest.mark.integration


@pytest.fixture
def _require_api_key() -> None:
    if not (settings.llm_api_key or os.environ.get("BSS_LLM_API_KEY")):
        pytest.skip("BSS_LLM_API_KEY unset — skipping real-network smoke test.")


async def test_single_turn_invokes_clock_tool(_require_api_key: None) -> None:
    """One turn that should prompt the LLM to call ``clock.now``."""
    session = Session(allow_destructive=False)
    reply = await session.ask(
        "What is the current system time? Use the clock tool to find out."
    )

    # Plain sanity.
    assert isinstance(reply, str)
    assert reply.strip(), "LLM returned empty reply"

    # At least one tool call happened during the turn.
    tool_calls = [m for m in session.history if isinstance(m, ToolMessage)]
    assert tool_calls, "No tool invocations observed — the LLM answered purely from priors"
    # The conversation must end on an AI message (the natural-language answer).
    ai_msgs = [m for m in session.history if isinstance(m, AIMessage)]
    assert ai_msgs, "No AIMessage in history"
