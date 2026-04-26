"""Landing / dashboard — login-gated `/` (V0_8_0 §3.4, §3.5).

v0.4 mounted ``/`` as the anonymous plan-cards landing. v0.8 makes
``/`` the customer dashboard:

* No session            -> 303 redirect to ``/auth/login`` (the
  ``requires_session`` dep handles this; ``/`` is NOT in
  ``security.PUBLIC_EXACT_PATHS``).
* Session, identity unlinked (verified email but never completed
  signup) -> renders ``dashboard_empty.html`` with a CTA into
  ``/plans`` to start the funnel. No customer record is created
  lazily — the empty-dashboard state is the deliberate placeholder.
* Session, identity linked -> renders ``dashboard.html``, a v0.10
  placeholder showing the customer email + "v0.10 will land lines
  here". Confirms the session resolution works end-to-end and gives
  v0.10 a stub to replace.

The public catalog browse moved to ``/plans`` in PR 4 — that's where
a signed-out visitor lands when they click "Browse plans" on /welcome.
"""

from __future__ import annotations

from bss_portal_auth import IdentityView, SessionView
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..security import requires_session
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _session: SessionView = Depends(requires_session),
) -> HTMLResponse:
    """Login-gated dashboard.

    The ``Depends(requires_session)`` handles the no-session case via
    ``RedirectToLogin``; the dependency resolves before this body runs.
    Inside the body we just branch on linked vs unlinked.
    """
    identity: IdentityView | None = getattr(request.state, "identity", None)
    if identity is None or identity.customer_id is None:
        return templates.TemplateResponse(
            request,
            "dashboard_empty.html",
            {
                "email": getattr(identity, "email", None),
            },
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": identity.email,
            "customer_id": identity.customer_id,
        },
    )
