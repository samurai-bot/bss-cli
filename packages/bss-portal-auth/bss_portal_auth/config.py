"""bss-portal-auth settings — env-driven, _REPO_ROOT pattern.

Mirrors packages/bss-middleware/config.py exactly. In Docker the env
comes from compose ``env_file: .env``; the ``env_file=`` path resolves
into site-packages and is silently skipped. At local pytest time the
path resolves to the repo root and ``.env`` is read directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server-side pepper for HMAC-ing OTP / magic-link / step-up tokens.
    # Never logged. Generated via `openssl rand -hex 32`. Rotation
    # invalidates all in-flight tokens (15-minute outage at most) — see
    # docs/runbooks/portal-auth.md.
    BSS_PORTAL_TOKEN_PEPPER: str = ""

    # Email adapter selection — 'logging' (writes to dev mailbox file),
    # 'noop' (test-only). 'smtp' is reserved for v1.0; selecting it
    # raises NotImplementedError at startup.
    BSS_PORTAL_EMAIL_ADAPTER: str = "logging"

    # Where the LoggingEmailAdapter writes OTPs + magic links for human
    # dev use. Tests do NOT read this file — they use NoopEmailAdapter.
    BSS_PORTAL_DEV_MAILBOX_PATH: str = "/tmp/bss-portal-mailbox.log"

    # Cookie security — only set 0 in local dev when serving over plain HTTP.
    BSS_PORTAL_DEV_INSECURE_COOKIE: int = 0

    # Token / session lifetimes (seconds). Defaults match V0_8_0.md §1.3.
    BSS_PORTAL_LOGIN_TOKEN_TTL_S: int = 15 * 60      # 15 min
    BSS_PORTAL_STEPUP_TOKEN_TTL_S: int = 5 * 60      # 5 min
    BSS_PORTAL_STEPUP_GRANT_TTL_S: int = 60          # 60 s — one-shot grant
    BSS_PORTAL_STEPUP_PENDING_TTL_S: int = 10 * 60   # 10 min — POST-body stash for replay
    BSS_PORTAL_SESSION_TTL_S: int = 24 * 60 * 60     # 24 h sliding window

    # Rate limits. Format kept as scalar ints — phase doc presents them
    # as "3/15min" but env scalars are easier to override per-deployment.
    BSS_PORTAL_LOGIN_PER_EMAIL_MAX: int = 3
    BSS_PORTAL_LOGIN_PER_EMAIL_WINDOW_S: int = 15 * 60
    BSS_PORTAL_LOGIN_PER_IP_MAX: int = 10
    BSS_PORTAL_LOGIN_PER_IP_WINDOW_S: int = 60 * 60
    BSS_PORTAL_VERIFY_PER_EMAIL_MAX: int = 10
    BSS_PORTAL_VERIFY_PER_EMAIL_WINDOW_S: int = 15 * 60
    BSS_PORTAL_STEPUP_PER_SESSION_MAX: int = 5
    BSS_PORTAL_STEPUP_PER_SESSION_WINDOW_S: int = 15 * 60
