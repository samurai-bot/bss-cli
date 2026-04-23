"""Fail-fast startup validator for BSS_API_TOKEN.

Called from each service's lifespan BEFORE any other setup. If the
token is unset, still the ``changeme`` sentinel from .env.example,
or shorter than 32 chars, the service refuses to start. Compose's
healthcheck surfaces the crash immediately.
"""

from __future__ import annotations

import structlog

from .config import Settings

log = structlog.get_logger(__name__)

_SENTINEL = "changeme"
_MIN_LENGTH = 32


def validate_api_token_present() -> None:
    """Raise RuntimeError if BSS_API_TOKEN is unset / sentinel / too short.

    Loads via pydantic-settings so .env values are picked up the same
    way services read other env config. Os.environ also works in tests
    (monkeypatch.setenv) because pydantic-settings reads os.environ first.
    """
    token = Settings().BSS_API_TOKEN
    if not token:
        raise RuntimeError(
            "BSS_API_TOKEN is unset; set it in .env before starting services. "
            "Generate via: openssl rand -hex 32"
        )
    if token == _SENTINEL:
        raise RuntimeError(
            "BSS_API_TOKEN is still the .env.example sentinel value "
            f"({_SENTINEL!r}); replace it with a real token. "
            "Generate via: openssl rand -hex 32"
        )
    if len(token) < _MIN_LENGTH:
        raise RuntimeError(
            f"BSS_API_TOKEN is too short ({len(token)} chars; need >={_MIN_LENGTH}). "
            "Generate via: openssl rand -hex 32"
        )
    log.info("auth.token.validated", length=len(token))
