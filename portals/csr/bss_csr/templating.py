"""Shared Jinja2Templates instance for the CSR portal.

Loader chain:
1. portal's own ``templates/`` (per-page layouts, partials, plus
   any local override of a shared partial)
2. ``bss_portal_ui``'s ``templates/`` (agent log widget +
   ``agent_event.html`` partial — shared with portals/self-serve)
"""

from __future__ import annotations

from pathlib import Path

from bss_portal_ui import TEMPLATE_DIR as SHARED_TEMPLATE_DIR
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

_LOCAL_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(_LOCAL_TEMPLATE_DIR))
templates.env.loader = ChoiceLoader(
    [
        FileSystemLoader(str(_LOCAL_TEMPLATE_DIR)),
        FileSystemLoader(str(SHARED_TEMPLATE_DIR)),
    ]
)
