"""Agent event → HTML partial projection + ID harvesting."""

from __future__ import annotations

from bss_orchestrator.session import (
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventPromptReceived,
    AgentEventToolCallCompleted,
    AgentEventToolCallStarted,
)

from bss_self_serve.agent_render import harvest_ids, project, render_html


def test_project_prompt_received_truncates_long_prompt() -> None:
    long_text = "x" * 500
    proj = project(AgentEventPromptReceived(prompt=long_text))
    assert proj.kind == "prompt"
    assert proj.icon == "→"
    assert len(proj.detail) <= 81  # 80 + ellipsis
    assert proj.detail_full == long_text


def test_project_tool_call_started_formats_args() -> None:
    proj = project(
        AgentEventToolCallStarted(
            name="customer.create",
            args={"name": "Ck", "email": "ck@example.com"},
            call_id="c1",
        )
    )
    assert proj.kind == "tool_started"
    assert "customer.create" in proj.title
    assert 'name="Ck"' in proj.title


def test_project_tool_call_completed_flags_error() -> None:
    ok = project(
        AgentEventToolCallCompleted(name="x", call_id="1", result="OK", is_error=False)
    )
    assert ok.icon == "←"
    assert ok.is_error is False

    bad = project(
        AgentEventToolCallCompleted(name="x", call_id="1", result="nope", is_error=True)
    )
    assert bad.icon == "⚠"
    assert bad.is_error is True


def test_project_final_message_shows_checkmark() -> None:
    proj = project(AgentEventFinalMessage(text="all done"))
    assert proj.kind == "final"
    assert proj.icon == "✓"


def test_project_error_variant() -> None:
    proj = project(AgentEventError(message="boom"))
    assert proj.kind == "error"
    assert proj.is_error is True


def test_render_html_returns_single_line() -> None:
    frag = render_html(AgentEventPromptReceived(prompt="hello"))
    assert "\n" not in frag
    assert "agent-event--prompt" in frag
    assert "→" in frag


def test_harvest_ids_picks_up_customer_order_subscription_lpa() -> None:
    text = (
        'Created customer CUST-042, order ORD-014, subscription SUB-007, '
        'activation code LPA:1$smdp.example.com$abc-123-def.'
    )
    out = harvest_ids(text)
    assert out["customer_id"] == "CUST-042"
    assert out["order_id"] == "ORD-014"
    assert out["subscription_id"] == "SUB-007"
    assert out["activation_code"].startswith("LPA:1$")


def test_harvest_ids_returns_empty_on_no_match() -> None:
    assert harvest_ids("nothing here") == {}
