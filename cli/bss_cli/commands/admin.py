"""`bss admin ...` — operator-only commands (reset, ops).

`bss admin reset` fans out to every service's ``/admin-api/v1/reset-operational-data``
endpoint, which is gated behind ``BSS_ALLOW_ADMIN_RESET=true`` on the target
service. This is deliberately CLI-only — the LLM tool surface does NOT
expose it, because scenario setup is an operator task, not a conversation.

Catalog (reference data), rating (no schema owned), and billing (not yet
implemented) are skipped. The CRM service owns both ``crm`` and
``inventory`` schemas so a single call to CRM handles both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer
from bss_clients import AdminClient
from bss_clients.errors import ClientError, NotFound, ServerError, Timeout
from bss_orchestrator.config import settings
from rich import print as rprint
from rich.table import Table

from .._runtime import run_async

app = typer.Typer(help="Operator tools — reset, ops.", no_args_is_help=True)


@dataclass(frozen=True)
class _Target:
    label: str
    url: str


def _targets() -> list[_Target]:
    """Services that own operational data. Order reflects dependency-friendly
    teardown (leaves first) but is not strictly required — each service's
    TRUNCATE ... CASCADE handles intra-schema FKs, and cross-schema references
    are by string id, not enforced by Postgres."""
    return [
        _Target("mediation", settings.mediation_url),
        _Target("subscription", settings.subscription_url),
        _Target("som", settings.som_url),
        _Target("com", settings.com_url),
        _Target("provisioning-sim", settings.provisioning_url),
        _Target("payment", settings.payment_url),
        _Target("crm (+ inventory)", settings.crm_url),
    ]


@app.command("reset")
def reset(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip interactive confirmation."),
    ] = False,
) -> None:
    """Wipe operational data across every BSS service.

    Reference data survives: catalog offerings, CSR agents, SLA policies,
    fault-injection config, and the MSISDN/eSIM pools (reset to
    ``available`` but rows preserved). Audit history is kept — a marker
    row with ``event_type=admin.operational_data_reset`` is inserted so
    scenarios can filter by ``occurred_at >= resetAt``.

    The Campaign OS co-tenant schema is physically unreachable: each
    service's admin router only lists tables in its own schema.
    """
    if not yes:
        rprint(
            "[bold yellow]About to wipe operational data across every BSS service.[/]\n"
            "Reference data (catalog, agents, pools, fault-injection) is preserved.\n"
            "[red]This is irreversible for the current run.[/]"
        )
        confirm = typer.prompt("Type 'reset' to confirm", default="", show_default=False)
        if confirm.strip().lower() != "reset":
            rprint("[yellow]Aborted.[/]")
            raise typer.Exit(code=1)

    results = run_async(_fanout(_targets()))
    _render(results)
    if any(r.status != "ok" for r in results):
        raise typer.Exit(code=2)


@dataclass
class _Result:
    target: _Target
    status: str  # "ok" | "error"
    detail: str
    response: dict | None = None


async def _fanout(targets: list[_Target]) -> list[_Result]:
    results: list[_Result] = []
    for target in targets:
        client = AdminClient(base_url=target.url)
        try:
            body = await client.reset_operational_data()
            results.append(_Result(target, "ok", "reset", body))
        except NotFound:
            results.append(_Result(target, "error", "404 — admin router not mounted"))
        except ClientError as e:
            # 403 from gate, 422 from validation, etc. Surface the status.
            results.append(_Result(target, "error", f"{e.status_code}: {e.detail}"))
        except Timeout:
            results.append(_Result(target, "error", "timeout"))
        except ServerError as e:
            results.append(_Result(target, "error", f"5xx: {e.detail}"))
        except Exception as e:  # pragma: no cover — surfaced to operator
            results.append(_Result(target, "error", f"{type(e).__name__}: {e}"))
        finally:
            await client.close()
    return results


def _render(results: list[_Result]) -> None:
    table = Table(title="bss admin reset")
    table.add_column("service")
    table.add_column("status")
    table.add_column("truncated")
    table.add_column("updated")
    table.add_column("detail")
    for r in results:
        truncated = "—"
        updated = "—"
        if r.response:
            schemas = r.response.get("schemas", [])
            truncated = ", ".join(
                f"{s['schema']}({len(s.get('truncated', []))})" for s in schemas
            ) or "—"
            updated = ", ".join(
                f"{s['schema']}({len(s.get('updated', []))})"
                for s in schemas
                if s.get("updated")
            ) or "—"
        colour = "green" if r.status == "ok" else "red"
        table.add_row(
            r.target.label,
            f"[{colour}]{r.status}[/]",
            truncated,
            updated,
            r.detail,
        )
    rprint(table)
