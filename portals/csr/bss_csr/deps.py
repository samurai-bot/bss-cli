"""FastAPI dependencies — operator session resolution.

Non-auth routes use ``Depends(require_operator)`` to enforce the
cookie. If missing or expired, the dependency raises a 303 redirect
to ``/login`` (HTMX boosts the redirect, browsers follow the location).
"""

from __future__ import annotations

from fastapi import Cookie, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from .session import SESSION_COOKIE, OperatorSession


class _RedirectExc(HTTPException):
    """An HTTPException wrapping a 303 redirect — caught by the FastAPI
    exception handler in main.py and converted to RedirectResponse."""

    def __init__(self, location: str) -> None:
        super().__init__(status_code=status.HTTP_303_SEE_OTHER, detail=location)
        self.location = location


async def require_operator(
    request: Request,
    bss_csr_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> OperatorSession:
    if not bss_csr_session:
        raise _RedirectExc("/login")
    store = request.app.state.session_store
    session = await store.get(bss_csr_session)
    if session is None:
        raise _RedirectExc("/login")
    return session


def install_redirect_handler(app) -> None:  # type: ignore[no-untyped-def]
    @app.exception_handler(_RedirectExc)
    async def _handle(_request: Request, exc: _RedirectExc) -> RedirectResponse:
        return RedirectResponse(url=exc.location, status_code=303)
