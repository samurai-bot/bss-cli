"""Interactive REPL — ``bss`` invoked with no subcommand.

A minimal readline-driven loop. Each turn is a ``Session.ask`` call, so
conversation history persists across turns in-memory. Exit with ``/exit``,
``/quit``, Ctrl-D, or Ctrl-C.

Slash commands:
    /exit, /quit   — leave the REPL
    /reset         — clear conversation history
    /help          — show this list
"""

from __future__ import annotations

import asyncio

from rich import print as rprint
from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from bss_orchestrator.clients import close_clients
from bss_orchestrator.config import settings
from bss_orchestrator.session import Session


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
            "[dim]·[/]   [dim]v0.1[/]"
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
        "[italic green]list active customers[/]   [dim]·[/]   "
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
                reply = loop.run_until_complete(session.ask(line))
            except Exception as e:  # pragma: no cover — surface at runtime
                rprint(f"[red]LLM error:[/] {e}")
                continue

            if not reply.strip():
                rprint("[yellow](no reply)[/]")
                continue
            rprint(Panel(reply, title="bss ai", border_style="cyan"))
    finally:
        try:
            loop.run_until_complete(close_clients())
        finally:
            loop.close()
