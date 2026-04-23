"""AuthProvider protocol and built-in implementations.

Every bss-clients client takes an AuthProvider at construction and calls it
on every outgoing request.

- ``NoAuthProvider`` — v0.1 default, no headers added. Used in tests.
- ``TokenAuthProvider`` — v0.3+ default everywhere in production wiring;
  injects ``X-BSS-API-Token: <BSS_API_TOKEN>`` so the receiving service's
  ``BSSApiTokenMiddleware`` accepts the request.

Phase 12 will add ``OAuth2ClientCredentialsProvider`` here. No hardcoded
auth headers anywhere else in the codebase.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Pluggable auth for service-to-service calls."""

    async def get_headers(self) -> dict[str, str]:
        """Return auth headers to inject into every outgoing request."""
        ...


class NoAuthProvider:
    """No-op provider used by tests and pre-v0.3 code paths."""

    async def get_headers(self) -> dict[str, str]:
        return {}


class TokenAuthProvider:
    """Injects ``X-BSS-API-Token`` on every outbound request.

    Construct with the shared ``BSS_API_TOKEN`` value (typically read from
    env in the caller's config layer). Empty token raises immediately —
    a valid client cannot exist with no token, by construction.
    """

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TokenAuthProvider requires a non-empty token")
        self._headers = {"X-BSS-API-Token": token}

    async def get_headers(self) -> dict[str, str]:
        return dict(self._headers)
