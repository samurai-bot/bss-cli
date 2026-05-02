"""``bss onboard`` — round-trip + atomic write tests.

Doesn't drive the interactive Typer session (that would require pty
work that's out of scope for v0.14). Instead exercises the underlying
``read_env_file`` / ``write_env_file`` helpers directly. These are the
parts that have correctness risk — the prompts are thin Rich shims.
"""

from __future__ import annotations

import os

import pytest

from bss_cli.commands.onboard import read_env_file, write_env_file


def test_read_env_empty_file_returns_empty_dict(tmp_path):
    f = tmp_path / "empty.env"
    f.write_text("")
    assert read_env_file(f) == {}


def test_read_env_missing_file_returns_empty_dict(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}


def test_read_env_skips_comments_and_blanks(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# this is a comment\n\nFOO=bar\n# another\nBAZ=qux\n")
    env = read_env_file(f)
    assert env == {"FOO": "bar", "BAZ": "qux"}


def test_read_env_strips_surrounding_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text('FOO="hello world"\nBAR=\'single quoted\'\nBAZ=plain\n')
    env = read_env_file(f)
    assert env == {
        "FOO": "hello world",
        "BAR": "single quoted",
        "BAZ": "plain",
    }


def test_write_env_creates_file_when_missing(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"FOO": "bar"})
    out = f.read_text()
    assert "FOO=bar" in out
    assert "# Added by `bss onboard`" in out


def test_write_env_preserves_comments_and_existing_order(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# Header comment\n"
        "FOO=old\n"
        "\n"
        "# Section comment\n"
        "BAR=baz\n"
    )
    write_env_file(f, {"FOO": "new", "BAR": "baz"})
    out = f.read_text()
    # Comments + ordering preserved; FOO updated in place.
    assert out.startswith("# Header comment\n")
    assert "FOO=new" in out
    assert "BAR=baz" in out
    assert "# Section comment" in out
    # No duplicate FOO line.
    assert out.count("FOO=") == 1


def test_write_env_appends_new_keys_at_end(tmp_path):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\n")
    write_env_file(f, {"FOO": "bar", "NEW_KEY": "added"})
    out = f.read_text()
    assert out.startswith("FOO=bar")
    assert "NEW_KEY=added" in out
    # Header for new keys is the marker line.
    assert "# Added by `bss onboard`" in out


def test_write_env_quotes_values_with_spaces(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"BSS_PORTAL_EMAIL_FROM": "BSS-CLI <noreply@x>"})
    out = f.read_text()
    assert 'BSS_PORTAL_EMAIL_FROM="BSS-CLI <noreply@x>"' in out


def test_write_env_atomic_replaces_existing_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("PRE_EXISTING=yes\n")
    write_env_file(f, {"PRE_EXISTING": "no", "ANOTHER": "value"})
    # Atomic replacement → no .env.tmp leftover.
    assert not (tmp_path / ".env.tmp").exists()
    env = read_env_file(f)
    assert env["PRE_EXISTING"] == "no"
    assert env["ANOTHER"] == "value"


def test_round_trip_resend_block(tmp_path):
    """Realistic case: an existing .env with non-email config, then
    onboard adds the four Resend env vars without touching the rest."""
    f = tmp_path / ".env"
    f.write_text(
        "# BSS-CLI dev .env\n"
        "BSS_DB_URL=postgresql+asyncpg://bss:bss@db:5432/bss\n"
        "BSS_API_TOKEN=0123456789abcdef0123456789abcdef\n"
    )
    env = read_env_file(f)
    env["BSS_PORTAL_EMAIL_PROVIDER"] = "resend"
    env["BSS_PORTAL_EMAIL_RESEND_API_KEY"] = "re_test_xxxxxxxxx"
    env["BSS_PORTAL_EMAIL_FROM"] = "BSS-CLI <noreply@mail.example.com>"
    env["BSS_PORTAL_EMAIL_RESEND_WEBHOOK_SECRET"] = "whsec_xxx"
    write_env_file(f, env)
    out = f.read_text()
    assert "BSS_DB_URL=" in out
    assert "BSS_API_TOKEN=" in out
    assert "BSS_PORTAL_EMAIL_PROVIDER=resend" in out
    assert "BSS_PORTAL_EMAIL_RESEND_API_KEY=re_test_xxxxxxxxx" in out
    assert 'BSS_PORTAL_EMAIL_FROM="BSS-CLI <noreply@mail.example.com>"' in out
    assert "# BSS-CLI dev .env" in out  # comment preserved


def test_unknown_domain_aborts():
    """Passing --domain=nonsense should exit cleanly."""
    from typer.testing import CliRunner

    from bss_cli.commands.onboard import app

    runner = CliRunner()
    result = runner.invoke(app, ["--domain", "nonsense"])
    assert result.exit_code == 2


def test_email_test_mode_drops_resend_creds(tmp_path, monkeypatch):
    """If operator switches from production back to test mode, stale
    Resend creds must be removed (otherwise a mode-mix is possible)."""
    from typer.testing import CliRunner

    from bss_cli.commands.onboard import app

    f = tmp_path / ".env"
    f.write_text(
        "BSS_PORTAL_EMAIL_PROVIDER=resend\n"
        "BSS_PORTAL_EMAIL_RESEND_API_KEY=re_test_old\n"
        "BSS_PORTAL_EMAIL_FROM=Old <a@b>\n"
    )
    runner = CliRunner()
    # Choose 'test' mode at the prompt.
    result = runner.invoke(
        app,
        ["--domain", "email", "--env-path", str(f)],
        input="test\n",
    )
    assert result.exit_code == 0, result.output
    env = read_env_file(f)
    assert env["BSS_PORTAL_EMAIL_PROVIDER"] == "logging"
    # Stale API key removed.
    assert "BSS_PORTAL_EMAIL_RESEND_API_KEY" not in env
