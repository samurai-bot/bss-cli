"""Route gating helpers — FastAPI dependencies + public-route allowlist.

The ``PortalSessionMiddleware`` already attached
``request.state.session`` / ``.identity`` / ``.customer_id`` (or None
on miss). These dependencies *enforce* the gates: each one raises a
``RedirectToLogin`` exception, caught by an exception handler and
turned into a 303 redirect.

Doctrine (V0_8_0.md §5):

* ``/welcome``, ``/plans``, ``/auth/*`` are the only paths reachable
  without a session. Adding a public route requires an entry in
  ``PUBLIC_PATH_PREFIXES`` + a test.
* ``request.state.customer_id`` is the only acceptable source of the
  customer id post-login. Routes never accept ``customer_id`` from
  query string or form input.
* Step-up tokens are forwarded as ``X-BSS-StepUp-Token`` header or
  ``step_up_token`` form field; ``requires_step_up`` consumes them
  via ``bss_portal_auth.consume_step_up_token``.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Final
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from bss_portal_auth import (
    IdentityView,
    SessionView,
    consume_step_up_token,
)


# ── Public-route allowlist ───────────────────────────────────────────────


PUBLIC_EXACT_PATHS: Final[frozenset[str]] = frozenset({
    "/health",
    "/health/ready",
    "/health/live",
    "/welcome",
    "/plans",
    # Convenience: `/` redirects to /welcome for anonymous visitors,
    # which the dashboard route does itself by raising RedirectToLogin.
})

PUBLIC_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/auth/",
    "/static/",
    "/portal-ui/static/",
    "/plans/",  # /plans/{id} detail page if/when added
)


def is_public_path(path: str) -> bool:
    """True iff ``path`` is reachable without a session.

    Doctrine: this list is the only allowlist. The route-gating
    dependencies live separately because every non-public route
    explicitly opts in via ``Depends(requires_session)``.
    """
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


# ── Redirect exception + handler ─────────────────────────────────────────


class RedirectToLogin(HTTPException):
    """Raised by a gating dep when no/invalid session is present."""

    def __init__(self, *, next_path: str | None = None) -> None:
        loc = "/auth/login"
        if next_path:
            loc = f"/auth/login?{urlencode({'next': next_path})}"
        super().__init__(status_code=status.HTTP_303_SEE_OTHER, detail=loc)
        self.location = loc


class StepUpRequired(HTTPException):
    """Raised by ``requires_step_up`` when no valid grant is present."""

    def __init__(self, *, action_label: str, next_path: str) -> None:
        params = urlencode({"action": action_label, "next": next_path})
        loc = f"/auth/step-up?{params}"
        super().__init__(status_code=status.HTTP_303_SEE_OTHER, detail=loc)
        self.location = loc


def install_redirect_handlers(app) -> None:  # type: ignore[no-untyped-def]
    """Install exception handlers that turn the redirects into 303 responses."""

    @app.exception_handler(RedirectToLogin)
    async def _login(_req: Request, exc: RedirectToLogin) -> RedirectResponse:
        return RedirectResponse(url=exc.location, status_code=303)

    @app.exception_handler(StepUpRequired)
    async def _stepup(_req: Request, exc: StepUpRequired) -> RedirectResponse:
        return RedirectResponse(url=exc.location, status_code=303)


# ── Dependencies ─────────────────────────────────────────────────────────


def _next_for(request: Request) -> str:
    """Build a `next=` parameter that the post-login flow can bounce to.

    Internal-paths only — never echo the absolute URL or query strings
    that contain user input. The /auth/login route validates this
    against the same is_public / known-prefix list before honouring it.
    """
    path = request.url.path
    qs = request.url.query
    return quote(f"{path}?{qs}", safe="/?=&") if qs else quote(path, safe="/")


def requires_session(request: Request) -> SessionView:
    """Gate: must have a live session. Raises RedirectToLogin if not."""
    sess = getattr(request.state, "session", None)
    if sess is None:
        raise RedirectToLogin(next_path=_next_for(request))
    return sess


def requires_verified_email(request: Request) -> IdentityView:
    """Gate: session present AND identity.email_verified_at set.

    The login flow stamps `email_verified_at` on first successful
    verify, so in practice this is equivalent to ``requires_session``
    today. Future flows (OAuth handoff, admin-impersonated session)
    may produce sessions with unverified identities; this dep keeps
    that distinction explicit.
    """
    sess = requires_session(request)
    identity: IdentityView | None = getattr(request.state, "identity", None)
    if identity is None or identity.email_verified_at is None:
        raise RedirectToLogin(next_path=_next_for(request))
    return identity


def requires_linked_customer(request: Request) -> str:
    """Gate: session + verified email + identity.customer_id is set.

    Returns the customer_id. Used by every post-first-order page.
    Verified-but-unlinked identities (created an account but bailed
    before completing signup) hit ``/`` and see the empty dashboard;
    they don't hit any route protected by this dep.
    """
    requires_verified_email(request)
    customer_id: str | None = getattr(request.state, "customer_id", None)
    if not customer_id:
        # Bounce to the dashboard, which is empty-state for unlinked.
        # We don't redirect to /plans because that would conflate
        # "unlinked identity wants to start signup" with "linked
        # customer asked for a feature that needs the customer_id".
        raise RedirectToLogin(next_path="/")
    return customer_id


def requires_step_up(action_label: str) -> Callable[[Request], Awaitable[None]]:
    """Dependency factory — consumes a one-shot step-up grant.

    Reads ``X-BSS-StepUp-Token`` header first, then ``step_up_token``
    form field (consumed during request parsing if applicable). On
    success: marks the grant consumed and returns. On failure: raises
    StepUpRequired so the route bounces to ``/auth/step-up``.
    """

    async def _dep(request: Request) -> None:
        sess = requires_session(request)

        token = request.headers.get("x-bss-stepup-token") or request.headers.get(
            "x-bss-step-up-token"
        )
        if token is None and request.method == "POST":
            try:
                form = await request.form()
                token = form.get("step_up_token")  # type: ignore[assignment]
            except Exception:
                token = None

        if not token:
            raise StepUpRequired(
                action_label=action_label, next_path=_next_for(request)
            )

        factory = getattr(request.app.state, "db_session_factory", None)
        if factory is None:
            raise RuntimeError(
                "app.state.db_session_factory not set — wire it in lifespan"
            )
        async with factory() as db:
            ok = await consume_step_up_token(
                db,
                session_id=sess.id,
                token=str(token),
                action_label=action_label,
            )
            await db.commit()

        if not ok:
            raise StepUpRequired(
                action_label=action_label, next_path=_next_for(request)
            )

    return _dep
