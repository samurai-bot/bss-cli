"""Shared Jinja2Templates instance + Response helper.

Routes import ``templates`` from here rather than constructing their
own Jinja environments. The loader chain is:
1. portal's own ``templates/`` (per-page templates, plus any local
   override of a shared partial)
2. ``bss_portal_ui``'s ``templates/`` (the agent log widget +
   ``agent_event.html`` partial — shared with portals/csr)
"""

from __future__ import annotations

from pathlib import Path

from bss_models import BSS_RELEASE
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
# v0.14 — every template gets ``bss_release`` for the brand-tag
# version display. Single source from ``bss_models.BSS_RELEASE``;
# bump there once per release.
templates.env.globals["bss_release"] = BSS_RELEASE
