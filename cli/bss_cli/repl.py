"""Interactive REPL — ``bss`` invoked with no subcommand.

Each turn streams agent events from ``Session.astream`` (v0.6+) so
tool-call observations on "show-shaped" tools (`subscription.get`,
`customer.get`, `order.get`, `catalog.list_offerings`,
`catalog.get_offering`, `inventory.esim.get_activation`,
`subscription.get_esim_activation`) render via the matching
:mod:`bss_cli.renderers` ASCII card *before* the model's text reply.

Without that hook the REPL only ever printed the model's prose summary
of a tool result — the polished CLI cards never showed up in the
LLM-native flow, even after v0.6 polished them.

Slash commands:
    /exit, /quit   — leave the REPL
    /reset         — clear conversation history
    /help          — show this list
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from rich import print as rprint
from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from bss_orchestrator.clients import close_clients
from bss_orchestrator.config import settings
from bss_orchestrator.session import (
    AgentEventError,
    AgentEventFinalMessage,
    AgentEventToolCallCompleted,
    Session,
)

from .renderers import (
    render_catalog,
    render_catalog_show,
    render_customer_360,
    render_esim_activation,
    render_order,
    render_subscription,
)


# Pieced from classic block letters — 8 lines tall, renders clean in 80-col.
_LOGO = r"""
 ██████╗  ███████╗ ███████╗     ██████╗ ██╗      ██╗
 ██╔══██╗ ██╔════╝ ██╔════╝    ██╔════╝ ██║      ██║
 ██████╔╝ ███████╗ ███████╗    ██║      ██║      ██║
 ██╔══██╗ ╚════██║ ╚════██║    ██║      ██║      ██║
 ██████╔╝ ███████║ ███████║    ╚██████╗ ███████╗ ██║
 ╚═════╝  ╚══════╝ ╚══════╝     ╚═════╝ ╚══════╝ ╚═╝"""


def _render_banner(allow_destructive: bool) -> Panel:
    logo = Text(_LOGO, style="bold cyan", no_wrap=True)
    tagline = Align.center(
        Text.from_markup(
            "[bold white]LLM-native Business Support System[/]   "
            "[dim]·[/]   [magenta]TMF[/] [dim]+[/] [magenta]SID[/]   "
            "[dim]·[/]   [dim]v0.6[/]"
        )
    )

    model_line = Align.center(
        Text.from_markup(
            f"[dim]model[/] [bold magenta]{settings.llm_model}[/]   "
            f"[dim]·[/]   [dim]actor[/] [cyan]{settings.llm_actor}[/]"
        )
    )

    hints = Text.from_markup(
        "  [bold]try[/]    "
        "[italic green]show the catalog[/]   [dim]·[/]   "
        "[italic green]show subscription SUB-0001[/]   [dim]·[/]   "
        "[italic green]what can you do?[/]\n"
        "  [bold]slash[/]  "
        "[cyan]/reset[/]   [dim]·[/]   "
        "[cyan]/help[/]   [dim]·[/]   "
        "[cyan]/exit[/]   [dim]·[/]   [dim]Ctrl-D / Ctrl-C to quit[/]"
    )

    parts: list = [
        logo,
        Text(""),
        tagline,
        model_line,
        Text(""),
        hints,
    ]
    if allow_destructive:
        parts += [
            Text(""),
            Align.center(
                Text.from_markup(
                    "[bold red on yellow] DESTRUCTIVE MODE [/] "
                    "[red]writes will execute — no confirmations[/]"
                )
            ),
        ]
    return Panel(
        Group(*parts),
        border_style="cyan",
        padding=(0, 1),
        title="[bold cyan]bss[/] [dim]·[/] [white]repl[/]",
        title_align="left",
        subtitle="[dim]type a request or a /command[/]",
        subtitle_align="right",
    )


# ─── Renderer dispatch ────────────────────────────────────────────────
#
# Map "show-shaped" tool names → callable that accepts the parsed JSON
# and returns the polished ASCII card. The dispatch is best-effort: if
# the tool result doesn't parse as JSON, or the renderer raises, the
# REPL silently skips and falls back to the model's text reply.

def _render_subscription(payload: dict) -> str:
    return render_subscription(payload)


def _render_subscription_list(payload: list) -> str:
    """Subscription list — stack one card per sub. ``[]`` → empty state."""
    if not payload:
        return "(no subscriptions)"
    return "\n".join(render_subscription(s) for s in payload)


def _render_customer(payload: dict) -> str:
    # The 360 renderer accepts subscriptions/cases/interactions but
    # works fine with just the customer dict — empty sections render
    # cleanly. The agent will typically have called other tools first
    # but we don't have visibility into those past results from a
    # single tool observation.
    return render_customer_360(payload)


def _render_customer_list(payload: list) -> str:
    """Compact table for ``customer.list`` results — id / name / email."""
    if not payload:
        return "(no customers)"
    rows: list[str] = ["── Customers " + "─" * 50, ""]
    rows.append(f"  {'ID':<15}  {'Name':<24}  {'Status':<10}  Email")
    rows.append(f"  {'─' * 15}  {'─' * 24}  {'─' * 10}  {'─' * 30}")
    for c in payload[:25]:
        ind = c.get("individual") or {}
        name = " ".join(
            s for s in [ind.get("givenName"), ind.get("familyName")] if s
        ).strip() or c.get("name", "—")
        email = ""
        for cm in c.get("contactMedium") or []:
            if cm.get("mediumType") == "email":
                email = cm.get("value", "")
                break
        rows.append(
            f"  {c.get('id', '?'):<15}  {name[:24]:<24}  "
            f"{c.get('status', '?'):<10}  {email[:30]}"
        )
    if len(payload) > 25:
        rows.append(f"  (+ {len(payload) - 25} more)")
    return "\n".join(rows)


def _render_order(payload: dict) -> str:
    return render_order(payload)


def _render_order_list(payload: list) -> str:
    """Compact table for ``order.list`` — id / state / customer / placed."""
    if not payload:
        return "(no orders)"
    rows: list[str] = ["── Orders " + "─" * 50, ""]
    rows.append(f"  {'ID':<14}  {'State':<14}  {'Customer':<16}  Placed")
    rows.append(f"  {'─' * 14}  {'─' * 14}  {'─' * 16}  {'─' * 19}")
    for o in payload[:25]:
        rows.append(
            f"  {o.get('id', '?'):<14}  {o.get('state', '?'):<14}  "
            f"{o.get('customerId', '—'):<16}  {(o.get('orderDate') or '')[:19]}"
        )
    if len(payload) > 25:
        rows.append(f"  (+ {len(payload) - 25} more)")
    return "\n".join(rows)


def _render_balance(payload: dict) -> str:
    """``subscription.get_balance`` — compact bundle bars only.

    Wraps the relevant fields in a tiny synthetic subscription dict so
    the existing renderer's bundle section does the work.
    """
    sub_id = payload.get("subscriptionId", "—")
    fake = {
        "id": sub_id,
        "state": payload.get("state", "?"),
        "balances": payload.get("balances") or [],
    }
    return render_subscription(fake)


def _render_catalog_list(payload: list) -> str:
    return render_catalog(payload)


def _render_catalog_show(payload: dict) -> str:
    return render_catalog_show(payload)


def _render_esim(payload: dict) -> str:
    return render_esim_activation(payload)


_RENDERER_DISPATCH: dict[str, Callable[[Any], str]] = {
    # Single-entity get
    "subscription.get": _render_subscription,
    "customer.get": _render_customer,
    "customer.find_by_msisdn": _render_customer,
    "order.get": _render_order,
    "catalog.get_offering": _render_catalog_show,
    "inventory.esim.get_activation": _render_esim,
    "subscription.get_esim_activation": _render_esim,
    # Lists / queries
    "subscription.list_for_customer": _render_subscription_list,
    "customer.list": _render_customer_list,
    "order.list": _render_order_list,
    "catalog.list_offerings": _render_catalog_list,
    # Balance — fold into the subscription card shape
    "subscription.get_balance": _render_balance,
}


def _maybe_render_tool_result(name: str, raw_result: str) -> str | None:
    """Return the polished card for a `*.get`-shaped tool, or None."""
    renderer = _RENDERER_DISPATCH.get(name)
    if renderer is None:
        return None
    try:
        payload = json.loads(raw_result)
    except (ValueError, TypeError):
        return None
    if not payload:
        return None
    try:
        return renderer(payload)
    except Exception:  # noqa: BLE001 — best-effort; never break the REPL
        return None


def _handle_slash(cmd: str, session: Session) -> bool:
    """Run a slash command. Returns True if the REPL should exit."""
    if cmd in {"/exit", "/quit"}:
        return True
    if cmd == "/reset":
        session.reset()
        rprint("[green]Conversation reset.[/]")
        return False
    if cmd == "/help":
        rprint(
            "[cyan]/reset[/] clear history  "
            "[cyan]/exit[/] leave  "
            "Anything else = send to LLM."
        )
        return False
    rprint(f"[yellow]Unknown command: {cmd}[/]")
    return False


async def _drive_turn(session: Session, line: str) -> None:
    """Stream one LLM turn, dispatching renderers on `*.get` tool results.

    When at least one renderer card prints, the model's text reply is
    suppressed — for ``show me X``-shaped questions the card IS the
    answer; the prose panel just restates it. For tool-less or
    no-renderer turns (`what can you do?`, `top up 5GB`, etc.) the
    text reply is shown as before.
    """
    final_text = ""
    error: str | None = None
    cards_shown = 0
    async for event in session.astream(line):
        if isinstance(event, AgentEventToolCallCompleted):
            # Prefer ``result_full`` (added v0.6) — the truncated
            # ``result`` is for log-widget display and won't reliably
            # parse as JSON for renderer dispatch.
            raw = event.result_full or event.result
            card = _maybe_render_tool_result(event.name, raw)
            if card:
                rprint(card)
                cards_shown += 1
        elif isinstance(event, AgentEventFinalMessage):
            final_text = event.text
        elif isinstance(event, AgentEventError):
            error = event.message
            break

    if error:
        rprint(f"[red]LLM error:[/] {error}")
        return
    if cards_shown:
        # The card is the answer; skip the redundant prose panel.
        return
    if not final_text.strip():
        rprint("[yellow](no reply)[/]")
        return
    rprint(Panel(final_text, title="bss ai", border_style="cyan"))


def run_repl(*, allow_destructive: bool = False) -> None:
    """Start the interactive LLM REPL. Blocks until the user quits."""

    try:
        session = Session(allow_destructive=allow_destructive)
    except RuntimeError as e:
        rprint(f"[red]LLM unavailable:[/] {e}")
        return

    rprint(_render_banner(allow_destructive))

    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                line = Prompt.ask("[bold]bss[/]").strip()
            except (EOFError, KeyboardInterrupt):
                rprint()
                break
            if not line:
                continue
            if line.startswith("/"):
                if _handle_slash(line, session):
                    break
                continue

            try:
                loop.run_until_complete(_drive_turn(session, line))
            except Exception as e:  # pragma: no cover — surface at runtime
                rprint(f"[red]LLM error:[/] {e}")
                continue
    finally:
        try:
            loop.run_until_complete(close_clients())
        finally:
            loop.close()
