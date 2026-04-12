"""Pydantic schema for scenario YAML.

The schema is intentionally narrow — v0.1 supports: variables, setup,
steps (action/ask/assert), teardown. No conditionals, loops, or scenario
composition. Those are Phase-11+ concerns per PHASE_10.md's scope guard.

Any unknown field at any level is a validation error — fail loud rather
than silently ignore typos in scenario files.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Setup / teardown
# ─────────────────────────────────────────────────────────────────────────────


class Setup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_operational_data: bool = False
    reset_sequences: bool = False
    freeze_clock_at: str | None = None  # ISO-8601 instant, optional tz
    variables: dict[str, Any] = Field(default_factory=dict)


class Teardown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unfreeze_clock: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Polling + operators (used by assertions and expect_final_state)
# ─────────────────────────────────────────────────────────────────────────────


class Poll(BaseModel):
    """Polling config for assertions against eventually-consistent state."""

    model_config = ConfigDict(extra="forbid")

    interval_ms: int = 200
    timeout_seconds: float = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Step types
# ─────────────────────────────────────────────────────────────────────────────


class _StepBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # Optional: assign captured values from tool result (jsonpath-ng expressions)
    capture: dict[str, str] = Field(default_factory=dict)


class ActionStep(_StepBase):
    """A deterministic tool call. ``action`` is a dotted registry name."""

    action: str
    args: dict[str, Any] = Field(default_factory=dict)


class AskStep(_StepBase):
    """An LLM-driven step. ``ask`` is natural language with `{{ var }}` interp."""

    ask: str
    timeout_seconds: float = 60.0
    expect_tools_called_include: list[str] = Field(default_factory=list)
    expect_tools_not_called: list[str] = Field(default_factory=list)
    expect_final_state: dict[str, Any] = Field(default_factory=dict)
    expect_event_sequence: list[str] = Field(default_factory=list)
    allow_clarification: bool = False


class AssertCall(BaseModel):
    """The `assert:` step block — call a read tool and check the shape."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    # Dot-path keys → expected scalar or operator dict
    expect: dict[str, Any] = Field(default_factory=dict)
    poll: Poll | None = None


class AssertStep(_StepBase):
    """Wraps an assert call so it carries a ``name`` in step reporting."""

    assert_: AssertCall = Field(alias="assert")

    @model_validator(mode="after")
    def _no_capture_on_assert(self):
        if self.capture:
            raise ValueError("assert: steps cannot use capture")
        return self


Step = ActionStep | AskStep | AssertStep


# ─────────────────────────────────────────────────────────────────────────────
# Top-level scenario
# ─────────────────────────────────────────────────────────────────────────────


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    setup: Setup = Field(default_factory=Setup)
    variables: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    teardown: Teardown = Field(default_factory=Teardown)


# Mode hints used by runner + CLI flags
LLMMode = Literal["auto", "disabled", "forced"]
