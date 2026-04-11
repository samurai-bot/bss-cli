"""AuthProvider protocol and NoAuthProvider default.

Every bss-clients client takes an AuthProvider at construction and calls it
on every outgoing request. v0.1 uses NoAuthProvider (no-op). Phase 12 swaps
in OAuth2ClientCredentialsProvider.

No hardcoded auth headers anywhere else in the codebase.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Pluggable auth for service-to-service calls."""

    async def get_headers(self) -> dict[str, str]:
        """Return auth headers to inject into every outgoing request."""
        ...


class NoAuthProvider:
    """Default for v0.1 — no authentication between services."""

    async def get_headers(self) -> dict[str, str]:
        return {}
