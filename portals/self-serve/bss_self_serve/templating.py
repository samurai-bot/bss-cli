"""Shared Jinja2Templates instance + Response helper.

Routes import ``templates`` from here rather than constructing their
own Jinja environments — keeps template loading predictable and
lets the test suite point at the bundled templates directory.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
