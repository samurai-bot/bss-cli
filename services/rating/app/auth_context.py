from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class AuthContext:
    actor: str = "system"
    tenant: str = "DEFAULT"
    roles: list[str] = field(default_factory=lambda: ["admin"])
    permissions: list[str] = field(default_factory=lambda: ["*"])
    channel: str = "system"


_current: ContextVar[AuthContext] = ContextVar("auth_context", default=AuthContext())


def current() -> AuthContext:
    return _current.get()


def set_for_request(actor: str, tenant: str, channel: str) -> None:
    _current.set(AuthContext(actor=actor, tenant=tenant, channel=channel))


def has_permission(permission: str) -> bool:
    ctx = current()
    return "*" in ctx.permissions or permission in ctx.permissions
