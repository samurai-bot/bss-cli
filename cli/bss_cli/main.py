"""`bss` — root Typer app. Direct commands + `bss ask` + `bss` REPL."""

from __future__ import annotations

from typing import Annotated

import typer
from bss_telemetry import configure_telemetry
from rich import print as rprint

from .commands import (
    admin as admin_cmd,
    case as case_cmd,
    catalog as catalog_cmd,
    clock as clock_cmd,
    customer as customer_cmd,
    inventory as inventory_cmd,
    order as order_cmd,
    payment as payment_cmd,
    prov as prov_cmd,
    scenario as scenario_cmd,
    som as som_cmd,
    subscription as subscription_cmd,
    ticket as ticket_cmd,
    trace as trace_cmd,
    usage as usage_cmd,
)

app = typer.Typer(
    name="bss",
    help="BSS-CLI — terminal-first, LLM-native telco BSS.",
    no_args_is_help=False,
)

# Direct command groups.
app.add_typer(customer_cmd.app, name="customer")
app.add_typer(case_cmd.app, name="case")
app.add_typer(ticket_cmd.app, name="ticket")
app.add_typer(order_cmd.app, name="order")
app.add_typer(subscription_cmd.app, name="subscription")
app.add_typer(catalog_cmd.app, name="catalog")
app.add_typer(payment_cmd.app, name="payment")
app.add_typer(usage_cmd.app, name="usage")
app.add_typer(prov_cmd.app, name="prov")
app.add_typer(som_cmd.app, name="som")
app.add_typer(inventory_cmd.app, name="inventory")
app.add_typer(clock_cmd.app, name="clock")
app.add_typer(trace_cmd.app, name="trace")
app.add_typer(admin_cmd.app, name="admin")
app.add_typer(scenario_cmd.app, name="scenario")


# `bss ask "..."` is a top-level command, not a subgroup.
@app.command("ask")
def ask_cmd(
    prompt: Annotated[str, typer.Argument(help="Natural-language request.")],
    allow_destructive: Annotated[
        bool, typer.Option("--allow-destructive", help="Permit destructive tool calls.")
    ] = False,
) -> None:
    """Single-shot LLM dispatch. Use the REPL (just `bss`) for multi-turn."""
    from .llm_runner import run_single_shot

    run_single_shot(prompt, allow_destructive=allow_destructive)


# `bss` with no subcommand → REPL.
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    allow_destructive: Annotated[
        bool, typer.Option("--allow-destructive")
    ] = False,
) -> None:
    # CLI is the root span for every `bss <cmd>` invocation. Without
    # this, traces would start at the first BSS service that the CLI
    # touches, hiding the CLI's own latency and breaking the
    # `audit.domain_event.trace_id` story for CLI-originated writes.
    configure_telemetry(service_name="cli")
    if ctx.invoked_subcommand is not None:
        return
    try:
        from .repl import run_repl
    except ImportError as e:
        rprint(f"[red]REPL unavailable: {e}[/]")
        raise typer.Exit(code=1)
    run_repl(allow_destructive=allow_destructive)


if __name__ == "__main__":  # pragma: no cover
    app()
