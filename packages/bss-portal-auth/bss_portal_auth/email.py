"""Email adapter — pluggable delivery channel for OTPs and magic links.

v0.8 ships:

* ``LoggingEmailAdapter`` — writes the OTP + magic link to a file
  (``BSS_PORTAL_DEV_MAILBOX_PATH``). Default in v0.8. ``tail -f`` the
  file in dev to "receive" mail. Rotation / pruning is the operator's
  problem.
* ``NoopEmailAdapter`` — for tests. Tests do NOT tail the dev-mailbox
  file (they would race across cases); they use
  ``bss_portal_auth.test_helpers.last_login_codes(email)`` instead.
* ``SmtpEmailAdapter`` — explicitly NOT implemented in v0.8. Stub
  raises NotImplementedError. v1.0 swaps it in.

The portal selects the adapter via ``BSS_PORTAL_EMAIL_ADAPTER`` env.
Anything other than 'logging' / 'noop' raises at startup.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

import structlog

from bss_clock import now as clock_now

log = structlog.get_logger(__name__)


class EmailAdapter(Protocol):
    """Three-method delivery surface used by the auth flows."""

    def send_login(self, email: str, otp: str, magic_link: str) -> None: ...
    def send_step_up(self, email: str, otp: str, action_label: str) -> None: ...
    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None: ...


class LoggingEmailAdapter:
    """Append-only dev mailbox — one log line per "send", plain text.

    Format is deliberately greppable so the hero scenarios can `tail`
    the file and pick out the most-recent OTP for a given email.
    Production-shape ``LoggingEmailAdapter`` is fine for a small MVNO
    in dev / staging; v1.0 swaps in real SMTP.

    Doctrine: this is the ONLY place where the OTP / magic-link
    plaintext is written anywhere outside the customer's inbox. The
    grep guard `rg 'log\\.(info|debug|warning).*(otp|magic_link|token)'
    packages/bss-portal-auth/` must stay empty — i.e. structlog never
    sees the secret.
    """

    def __init__(self, mailbox_path: str | Path):
        self.path = Path(mailbox_path)
        # Touch parent dir; the file itself is created on first write.
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, lines: list[str]) -> None:
        ts = clock_now().isoformat()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {ts} ===\n")
            for line in lines:
                fh.write(line + "\n")

    def send_login(self, email: str, otp: str, magic_link: str) -> None:
        self._append(
            [
                f"To: {email}",
                "Subject: Your bss-cli portal login code",
                "",
                f"OTP: {otp}",
                f"Magic link: {magic_link}",
                "",
                "Code expires in 15 minutes.",
            ]
        )
        # Structured log carries length only, never the secret itself.
        log.info(
            "portal_auth.email.login_sent",
            adapter="logging",
            email_domain=email.split("@", 1)[-1] if "@" in email else "?",
        )

    def send_step_up(self, email: str, otp: str, action_label: str) -> None:
        self._append(
            [
                f"To: {email}",
                f"Subject: Confirm action: {action_label}",
                "",
                f"OTP: {otp}",
                f"Action: {action_label}",
                "",
                "Code expires in 5 minutes.",
            ]
        )
        log.info(
            "portal_auth.email.step_up_sent",
            adapter="logging",
            action=action_label,
        )

    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None:
        self._append(
            [
                f"To: {new_email}",
                "Subject: Verify your new email for bss-cli",
                "",
                f"OTP: {otp}",
                f"Magic link: {magic_link}",
            ]
        )
        log.info("portal_auth.email.change_sent", adapter="logging")


class NoopEmailAdapter:
    """Test adapter — keeps the most recent code for each (email, kind)
    in process memory. Tests inspect via
    ``bss_portal_auth.test_helpers.last_login_codes(email)``.
    """

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, str | datetime]] = {}

    def send_login(self, email: str, otp: str, magic_link: str) -> None:
        self.records[(email, "login")] = {
            "otp": otp,
            "magic_link": magic_link,
            "ts": clock_now(),
        }

    def send_step_up(self, email: str, otp: str, action_label: str) -> None:
        self.records[(email, f"step_up:{action_label}")] = {
            "otp": otp,
            "action_label": action_label,
            "ts": clock_now(),
        }

    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None:
        self.records[(new_email, "email_change")] = {
            "otp": otp,
            "magic_link": magic_link,
            "ts": clock_now(),
        }


class SmtpEmailAdapter:
    """Reserved for v1.0. Selecting it raises at construction time so
    nothing silently falls back to no-op delivery in production.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "SmtpEmailAdapter is reserved for v1.0. Use LoggingEmailAdapter "
            "(BSS_PORTAL_EMAIL_ADAPTER=logging) for dev/staging until then."
        )

    def send_login(self, email: str, otp: str, magic_link: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def send_step_up(self, email: str, otp: str, action_label: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None:  # pragma: no cover
        raise NotImplementedError


def select_adapter(name: str, mailbox_path: str | Path) -> EmailAdapter:
    """Resolve ``BSS_PORTAL_EMAIL_ADAPTER`` -> concrete adapter.

    Unknown values raise — fail fast at portal startup, never silently
    downgrade to no-op delivery.
    """
    name = name.lower()
    if name == "logging":
        return LoggingEmailAdapter(mailbox_path)
    if name == "noop":
        return NoopEmailAdapter()
    if name == "smtp":
        # Constructor raises — preserves "fail-fast at startup" doctrine.
        return SmtpEmailAdapter()
    raise RuntimeError(
        f"Unknown BSS_PORTAL_EMAIL_ADAPTER={name!r}; expected "
        "'logging' (default), 'noop' (tests), or 'smtp' (v1.0+)."
    )
