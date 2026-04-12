"""`bss trace ...` — audit event query.

v0.1 has no query endpoint on `audit.domain_event` — that ships in Phase 11
alongside OTel. These commands print a structured not-implemented notice.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import print as rprint

app = typer.Typer(help="Query domain events + traces (Phase 11).", no_args_is_help=True)


@app.command("events")
def events(
    aggregate: Annotated[str, typer.Option("--aggregate")],
    id_: Annotated[str, typer.Option("--id")],
) -> None:
    """Print audit events for an aggregate. Phase 11 lights this up."""
    rprint(
        f"[yellow]trace.events not implemented in v0.1 — ships with Phase 11.[/]\n"
        f"requested: aggregate={aggregate} id={id_}"
    )
    raise typer.Exit(code=2)
