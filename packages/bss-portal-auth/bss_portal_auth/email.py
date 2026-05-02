"""Email adapter — pluggable delivery channel for OTPs and magic links.

v0.14 ships:

* ``LoggingEmailAdapter`` — writes the OTP + magic link to a file
  (``BSS_PORTAL_DEV_MAILBOX_PATH``). Default in dev. ``tail -f`` the
  file in dev to "receive" mail.
* ``NoopEmailAdapter`` — for tests. Tests do NOT tail the dev-mailbox
  file (they would race across cases); they use
  ``bss_portal_auth.test_helpers.last_login_codes(adapter, email)``
  instead.
* ``ResendEmailAdapter`` — v0.14 production adapter. Sync HTTP call
  via the ``resend`` Python SDK; structured logging records the
  Resend ``msg_*`` id and latency for forensic correlation with
  inbound webhook events (``/webhooks/resend`` → ``integrations.webhook_event``).
* ``SmtpEmailAdapter`` — explicitly NOT implemented. Stub raises
  NotImplementedError. Reserved for post-v0.16.

The portal selects the adapter via ``BSS_PORTAL_EMAIL_PROVIDER`` env
(renamed from ``BSS_PORTAL_EMAIL_ADAPTER`` in v0.14; old name still
read with a DeprecationWarning until v0.16). Anything other than
the listed values raises at startup.
"""

from __future__ import annotations

import time
import warnings
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
    in dev / staging; v0.14 swaps ``ResendEmailAdapter`` in for prod.

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


class ResendEmailAdapter:
    """v0.14 production adapter — sends via Resend's HTTPS API.

    Construction validates the API key + sender; instantiation does NOT
    make a network call. The first ``send_*`` triggers the SDK's HTTPS
    call. Sync (the SDK is sync; preserves existing call-site shape).

    Each ``send_*`` call records to structlog with:

    * ``provider="resend"``
    * ``operation`` (one of ``send_login`` / ``send_step_up`` /
      ``send_email_change``)
    * ``provider_call_id`` (the ``msg_*`` id Resend returns)
    * ``latency_ms``
    * ``success`` (bool)
    * ``email_domain`` only — never the full address (PII), never the
      OTP / magic-link.

    The structured log line is the forensic correlation point with
    inbound webhook events (``/webhooks/resend`` → ``email.delivered``,
    ``email.bounced``, etc.). Both share the ``provider_call_id``.

    Forward path (v0.15+): once the adapter Protocol goes async, calls
    will also write a row to ``integrations.external_call``. v0.14
    leaves that for the async migration.
    """

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
    ) -> None:
        if not api_key:
            raise ValueError("ResendEmailAdapter requires a non-empty api_key")
        if not from_address:
            raise ValueError(
                "ResendEmailAdapter requires from_address "
                "(BSS_PORTAL_EMAIL_FROM, e.g. 'BSS-CLI <noreply@mail.example.com>')"
            )
        self._api_key = api_key
        self._from = from_address
        # Lazy import — keep `import bss_portal_auth.email` cheap and avoid
        # forcing the resend SDK on test contexts using NoopEmailAdapter.
        import resend

        resend.api_key = api_key
        self._resend = resend

    # ── public API (sync) ────────────────────────────────────────────

    def send_login(self, email: str, otp: str, magic_link: str) -> None:
        body_html = (
            f"<p>Your login code: <strong>{otp}</strong></p>"
            f"<p>Or click: <a href=\"{magic_link}\">sign in</a></p>"
            f"<p>Code expires in 15 minutes.</p>"
        )
        body_text = (
            f"OTP: {otp}\n"
            f"Magic link: {magic_link}\n\n"
            f"Code expires in 15 minutes."
        )
        self._send(
            operation="send_login",
            to=email,
            subject="Your bss-cli portal login code",
            html=body_html,
            text=body_text,
        )

    def send_step_up(self, email: str, otp: str, action_label: str) -> None:
        body_html = (
            f"<p>Action: <strong>{action_label}</strong></p>"
            f"<p>Confirmation code: <strong>{otp}</strong></p>"
            f"<p>Code expires in 5 minutes.</p>"
        )
        body_text = (
            f"Action: {action_label}\n"
            f"OTP: {otp}\n\n"
            f"Code expires in 5 minutes."
        )
        self._send(
            operation="send_step_up",
            to=email,
            subject=f"Confirm action: {action_label}",
            html=body_html,
            text=body_text,
        )

    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None:
        body_html = (
            f"<p>Confirm your new email by entering this code: "
            f"<strong>{otp}</strong></p>"
            f"<p>Or click: <a href=\"{magic_link}\">verify</a></p>"
        )
        body_text = (
            f"OTP: {otp}\n"
            f"Magic link: {magic_link}"
        )
        self._send(
            operation="send_email_change",
            to=new_email,
            subject="Verify your new email for bss-cli",
            html=body_html,
            text=body_text,
        )

    # ── internal ─────────────────────────────────────────────────────

    def _send(
        self,
        *,
        operation: str,
        to: str,
        subject: str,
        html: str,
        text: str,
    ) -> None:
        """Single Resend HTTPS call with structured-log forensic record."""
        params = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        domain = to.split("@", 1)[-1] if "@" in to else "?"
        start = time.monotonic()
        try:
            result = self._resend.Emails.send(params)
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            log.warning(
                "portal_auth.email.send_failed",
                adapter="resend",
                operation=operation,
                email_domain=domain,
                latency_ms=elapsed,
                error_class=type(exc).__name__,
                error_message=str(exc)[:200],
            )
            raise
        elapsed = int((time.monotonic() - start) * 1000)
        # Resend returns a dict-like with at least an ``id`` field.
        provider_call_id = (
            result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        )
        log.info(
            "portal_auth.email.sent",
            adapter="resend",
            operation=operation,
            email_domain=domain,
            latency_ms=elapsed,
            provider_call_id=provider_call_id,
        )


class SmtpEmailAdapter:
    """Reserved for post-v0.16. Selecting it raises at construction time so
    nothing silently falls back to no-op delivery in production.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "SmtpEmailAdapter is reserved for post-v0.16. Use ResendEmailAdapter "
            "(BSS_PORTAL_EMAIL_PROVIDER=resend) for production, or LoggingEmailAdapter "
            "(BSS_PORTAL_EMAIL_PROVIDER=logging) for dev."
        )

    def send_login(self, email: str, otp: str, magic_link: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def send_step_up(self, email: str, otp: str, action_label: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def send_email_change_verification(
        self, new_email: str, otp: str, magic_link: str
    ) -> None:  # pragma: no cover
        raise NotImplementedError


def select_adapter(
    name: str,
    mailbox_path: str | Path,
    *,
    resend_api_key: str = "",
    from_address: str = "",
) -> EmailAdapter:
    """Resolve ``BSS_PORTAL_EMAIL_PROVIDER`` -> concrete adapter.

    Unknown values raise — fail fast at portal startup, never silently
    downgrade to no-op delivery.
    """
    name = name.lower()
    if name == "logging":
        return LoggingEmailAdapter(mailbox_path)
    if name == "noop":
        return NoopEmailAdapter()
    if name == "resend":
        if not resend_api_key:
            raise RuntimeError(
                "BSS_PORTAL_EMAIL_PROVIDER=resend requires "
                "BSS_PORTAL_EMAIL_RESEND_API_KEY to be set."
            )
        if not from_address:
            raise RuntimeError(
                "BSS_PORTAL_EMAIL_PROVIDER=resend requires "
                "BSS_PORTAL_EMAIL_FROM to be set "
                "(e.g. 'BSS-CLI <noreply@mail.example.com>')."
            )
        return ResendEmailAdapter(
            api_key=resend_api_key, from_address=from_address
        )
    if name == "smtp":
        # Constructor raises — preserves "fail-fast at startup" doctrine.
        return SmtpEmailAdapter()
    raise RuntimeError(
        f"Unknown BSS_PORTAL_EMAIL_PROVIDER={name!r}; expected "
        "'logging' (default), 'noop' (tests), 'resend' (v0.14+), or "
        "'smtp' (reserved post-v0.16)."
    )


def resolve_provider_name(
    *, provider: str, legacy_adapter: str
) -> str:
    """Reconcile new ``BSS_PORTAL_EMAIL_PROVIDER`` with legacy
    ``BSS_PORTAL_EMAIL_ADAPTER``.

    * Both empty → default to ``"logging"``.
    * Only legacy set → emit DeprecationWarning, use legacy value.
    * Only new set → use it.
    * Both set → use new; warn if they differ (legacy ignored).

    Removed in v0.16. Greppable: this function is the only place that
    reads ``BSS_PORTAL_EMAIL_ADAPTER``.
    """
    new = (provider or "").strip()
    old = (legacy_adapter or "").strip()
    if not new and not old:
        return "logging"
    if not new and old:
        warnings.warn(
            "BSS_PORTAL_EMAIL_ADAPTER is deprecated; rename to "
            "BSS_PORTAL_EMAIL_PROVIDER. Old name removed in v0.16.",
            DeprecationWarning,
            stacklevel=2,
        )
        return old
    if new and old and new != old:
        warnings.warn(
            f"Both BSS_PORTAL_EMAIL_PROVIDER ({new!r}) and "
            f"BSS_PORTAL_EMAIL_ADAPTER ({old!r}) are set with different "
            "values; using BSS_PORTAL_EMAIL_PROVIDER. Remove the old "
            "name from .env to silence this warning.",
            DeprecationWarning,
            stacklevel=2,
        )
    return new
