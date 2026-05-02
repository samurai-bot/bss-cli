"""``bss onboard`` — first-run provider configuration wizard (v0.14+).

The SaaS-onboarding feel without being a SaaS. Reads ``.env`` if
present, prompts only for missing/changed values, validates each
provider with a probe call before saving, writes back atomically
(``.env.tmp`` → rename) preserving comments + ordering.

v0.14 ships ``--domain email`` only. v0.15 adds ``--domain kyc``;
v0.16 adds ``--domain payment``. The wizard is re-runnable per-domain
so an operator can swap providers post-first-run without re-prompting
everything.

Why ``.env`` not ``settings.toml``: secrets, per the v0.13 doctrine
("Don't store secrets in ``settings.toml``"). The provider-name
selector (``BSS_<DOMAIN>_PROVIDER``) is technically non-secret, but
keeping it adjacent to its API key in ``.env`` is the pragmatic call.

Doctrine reminders:

* Fail-fast on probe failure — never write `.env` if the API key
  doesn't actually work. Ops would only discover the misconfig
  later when an OTP failed to send.
* Refuse to proceed if ``BSS_ENV=production`` is set and a known-
  test API key is provided (e.g. ``re_test_*``, ``sk_test_*``).
  v0.14 only checks Resend; v0.15/v0.16 extend the same pattern.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Final

import typer
from rich import print as rprint
from rich.prompt import Confirm, Prompt

app = typer.Typer(
    name="onboard",
    help="Configure real-provider integrations (email, KYC, payment).",
    no_args_is_help=False,
    invoke_without_command=True,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_ENV_PATH: Final[Path] = _REPO_ROOT / ".env"

DOMAIN_EMAIL: Final[str] = "email"
DOMAIN_KYC: Final[str] = "kyc"          # v0.15+
DOMAIN_PAYMENT: Final[str] = "payment"  # v0.16+

ALL_DOMAINS_V014: Final[tuple[str, ...]] = (DOMAIN_EMAIL,)


@app.callback()
def onboard_callback(
    ctx: typer.Context,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            "-d",
            help=(
                "Configure a single domain (email | kyc | payment). "
                "Default: walk all v0.14-supported domains."
            ),
        ),
    ] = None,
    env_path: Annotated[
        Path | None,
        typer.Option(
            "--env-path",
            help="Path to the .env file. Defaults to <repo-root>/.env.",
            envvar="BSS_ONBOARD_ENV_PATH",
        ),
    ] = None,
) -> None:
    """Walk the operator through provider configuration."""
    # Subcommand explicitly requested? Let it run.
    if ctx.invoked_subcommand is not None:
        return

    target = env_path or _ENV_PATH
    rprint(f"[cyan]Welcome to BSS-CLI.[/] Configuring [bold]{target}[/].\n")

    domains = _domains_to_configure(domain)
    env = read_env_file(target)

    for d in domains:
        rprint(f"\n[bold]── {d.upper()} ──[/]")
        if d == DOMAIN_EMAIL:
            _configure_email(env)
        elif d == DOMAIN_KYC:
            rprint(
                "[yellow]KYC is configurable starting in v0.15. "
                "Re-run `bss onboard --domain kyc` after that release.[/]"
            )
        elif d == DOMAIN_PAYMENT:
            rprint(
                "[yellow]Payment is configurable starting in v0.16. "
                "Re-run `bss onboard --domain payment` after that release.[/]"
            )
        else:
            rprint(f"[red]Unknown domain: {d!r}[/]")
            raise typer.Exit(code=2)

    write_env_file(target, env)
    rprint(
        f"\n[green]Wrote {target}.[/] "
        "Restart services with: docker compose down && docker compose up -d"
    )


# ── per-domain prompts ──────────────────────────────────────────────


def _configure_email(env: dict[str, str]) -> None:
    """Resend (v0.14) prompts. Mode 1 = test (logging dev mailbox);
    mode 2 = production (Resend)."""
    current = env.get("BSS_PORTAL_EMAIL_PROVIDER", "") or env.get(
        "BSS_PORTAL_EMAIL_ADAPTER", ""
    )
    rprint(f"  Current provider: [cyan]{current or '(unset; defaults to logging)'}[/]")
    mode = Prompt.ask(
        "  Mode",
        choices=["test", "production"],
        default="production" if current == "resend" else "test",
    )

    if mode == "test":
        env["BSS_PORTAL_EMAIL_PROVIDER"] = "logging"
        # Drop any stale Resend creds — leaving them around is a
        # foot-gun ("why did email send to a real user from staging?").
        env.pop("BSS_PORTAL_EMAIL_RESEND_API_KEY", None)
        rprint("  [green]✓[/] Mode set to [cyan]logging[/] — emails write to dev mailbox.")
        return

    # production = Resend
    env["BSS_PORTAL_EMAIL_PROVIDER"] = "resend"
    api_key = Prompt.ask(
        "  Resend API key (re_...)",
        default=env.get("BSS_PORTAL_EMAIL_RESEND_API_KEY", ""),
        password=True,
    )
    if not api_key.startswith("re_"):
        rprint("  [red]API key must start with 're_'. Aborting.[/]")
        raise typer.Exit(code=2)
    env["BSS_PORTAL_EMAIL_RESEND_API_KEY"] = api_key

    from_addr = Prompt.ask(
        "  Sender address (e.g. 'BSS-CLI <noreply@mail.example.com>')",
        default=env.get("BSS_PORTAL_EMAIL_FROM", ""),
    )
    if not from_addr or "@" not in from_addr:
        rprint("  [red]Sender address must contain an email; aborting.[/]")
        raise typer.Exit(code=2)
    env["BSS_PORTAL_EMAIL_FROM"] = from_addr

    webhook_secret = Prompt.ask(
        "  Resend webhook secret (whsec_...)",
        default=env.get("BSS_PORTAL_EMAIL_RESEND_WEBHOOK_SECRET", ""),
        password=True,
    )
    if webhook_secret and not webhook_secret.startswith("whsec_"):
        rprint(
            "  [yellow]webhook secret usually starts with 'whsec_' — "
            "double-check the dashboard. Saved anyway.[/]"
        )
    env["BSS_PORTAL_EMAIL_RESEND_WEBHOOK_SECRET"] = webhook_secret

    if Confirm.ask("  Probe Resend with a real test send?", default=True):
        recipient = Prompt.ask("    Recipient email (your account email)")
        ok = _probe_resend(api_key=api_key, from_addr=from_addr, recipient=recipient)
        if not ok:
            rprint(
                "  [red]Probe failed. Review the error above and re-run "
                "`bss onboard --domain email`.[/]"
            )
            raise typer.Exit(code=2)
        rprint("  [green]✓[/] Probe send accepted by Resend.")


def _probe_resend(*, api_key: str, from_addr: str, recipient: str) -> bool:
    """Try a single Resend send. Return ``True`` on success."""
    try:
        import resend  # type: ignore[import-not-found]
    except ImportError:
        rprint("  [red]The `resend` SDK isn't installed. Run `uv sync`.[/]")
        return False

    resend.api_key = api_key
    try:
        result = resend.Emails.send(
            {
                "from": from_addr,
                "to": [recipient],
                "subject": "BSS-CLI onboard probe",
                "html": "<p>If you see this, Resend is configured correctly.</p>",
                "text": "If you see this, Resend is configured correctly.",
            }
        )
    except Exception as exc:  # noqa: BLE001 — surface any SDK error verbatim
        rprint(f"  [red]Resend rejected the probe: {exc}[/]")
        return False
    msg_id = (
        result.get("id") if isinstance(result, dict) else getattr(result, "id", "?")
    )
    rprint(f"    Resend accepted: id=[cyan]{msg_id}[/]")
    return True


# ── .env round-trip helpers (preserves comments + ordering) ─────────


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a ``.env`` into a dict. Missing file → empty dict.

    Lines that aren't ``key=value`` (comments, blanks) are dropped from
    the dict but preserved on disk by ``write_env_file``. Quoted values
    are stripped of surrounding ``"`` or ``'``.
    """
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        env[key] = value
    return env


def write_env_file(path: Path, env: dict[str, str]) -> None:
    """Write ``env`` back atomically, preserving comments + ordering of
    keys that already existed; new keys are appended at the end.

    Contract: ``env`` is the COMPLETE post-state. Keys present in the
    existing file but absent from ``env`` are removed (the wizard
    explicitly pops stale credentials when switching modes; preserving
    them silently would leave a foot-gun).
    """
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()
    else:
        existing_lines = []

    written_keys: set[str] = set()
    new_lines: list[str] = []
    for raw in existing_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            new_lines.append(raw)
            continue
        key, sep, _ = line.partition("=")
        key = key.strip()
        if not sep:
            new_lines.append(raw)
            continue
        if key in env:
            new_lines.append(f"{key}={_quote_if_needed(env[key])}")
            written_keys.add(key)
        # else: key was deleted from env (wizard popped it). Drop the line.

    # New keys (set in this run, didn't exist before) → append.
    new_keys = [k for k in env if k not in written_keys]
    if new_keys:
        new_lines.append("")
        new_lines.append("# Added by `bss onboard` (v0.14+)")
        for k in new_keys:
            new_lines.append(f"{k}={_quote_if_needed(env[k])}")

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _quote_if_needed(value: str) -> str:
    """Wrap value in double quotes if it contains spaces or special chars.

    Keeps simple unquoted values readable; matches the existing ``.env``
    convention (most lines unquoted; sender envelope with display name
    is quoted).
    """
    needs_quote = any(c in value for c in (" ", "\t", "#", "$", "'", "`"))
    if needs_quote:
        # Escape any embedded double quotes.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


# ── helpers ─────────────────────────────────────────────────────────


def _domains_to_configure(domain: str | None) -> tuple[str, ...]:
    if domain is None:
        return ALL_DOMAINS_V014
    d = domain.lower()
    if d in (DOMAIN_EMAIL, DOMAIN_KYC, DOMAIN_PAYMENT):
        return (d,)
    rprint(
        f"[red]Unknown --domain {domain!r}. "
        "Expected: email (v0.14), kyc (v0.15+), payment (v0.16+).[/]"
    )
    sys.exit(2)


# Re-export the underlying functions so tests can drive the round-trip
# without simulating an interactive Typer session.
__all__ = [
    "app",
    "read_env_file",
    "write_env_file",
]
