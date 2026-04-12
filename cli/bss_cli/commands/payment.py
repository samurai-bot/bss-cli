"""`bss payment ...` — payment-method + charge commands."""

from __future__ import annotations

from typing import Annotated

import typer
from bss_clients import PolicyViolationFromServer
from bss_orchestrator.clients import get_clients
from rich import print as rprint

from .._runtime import run_async

app = typer.Typer(help="Payment methods + payment attempts.", no_args_is_help=True)


@app.command("add-card")
def add_card(
    customer: Annotated[str, typer.Option("--customer")],
    card: Annotated[str, typer.Option("--card", help="16-digit PAN (tokenised by CLI).")],
) -> None:
    """Tokenise a PAN via /dev/tokenize and attach it as a payment method."""

    async def _do() -> None:
        c = get_clients()
        tok = await c.payment.dev_tokenize_card(card)
        pm = await c.payment.create_payment_method(
            customer_id=customer,
            card_token=tok["cardToken"],
            last4=tok["last4"],
            brand=tok["brand"],
        )
        rprint(f"[green]Added[/] {pm['id']}  {pm.get('brand')}•••{pm.get('last4')}")

    _run_safely(_do())


@app.command("list-methods")
def list_methods(customer: Annotated[str, typer.Option("--customer")]) -> None:
    """List payment methods for a customer."""

    async def _do() -> None:
        c = get_clients()
        for pm in await c.payment.list_methods(customer):
            rprint(
                f"{pm['id']:<9} {pm.get('brand', ''):<6}•••{pm.get('last4', '')}  "
                f"{pm.get('expMonth', '?'):02}/{pm.get('expYear', '????')}"
            )

    _run_safely(_do())


@app.command("remove-method")
def remove_method(
    method_id: Annotated[str, typer.Argument()],
    allow_destructive: Annotated[bool, typer.Option("--allow-destructive")] = False,
) -> None:
    """Remove a payment method (destructive)."""
    if not allow_destructive:
        rprint("[yellow]remove-method is gated behind --allow-destructive.[/]")
        raise typer.Exit(code=2)

    async def _do() -> None:
        c = get_clients()
        out = await c.payment.remove_method(method_id)
        rprint(f"[green]Removed[/] {out.get('id')}")

    _run_safely(_do())


def _run_safely(coro) -> None:
    try:
        run_async(coro)
    except PolicyViolationFromServer as e:
        rprint(f"[red]POLICY_VIOLATION[/] [bold]{e.rule}[/]  {e.message}")
        raise typer.Exit(code=2)
