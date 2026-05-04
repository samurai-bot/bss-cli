#!/usr/bin/env python3
"""Capture v0.18+ portal screenshots via playwright headless.

Run from repo root:
    uv run python docs/screenshots/capture_portals.py

Prereqs (see CAPTURE.md):
    uv pip install playwright
    uv run python -m playwright install chromium

The script targets the post-v0.13 surfaces:

* portal-self-serve (port 9001) — public /welcome, /plans
* portal-csr (port 9002) — v0.13 cockpit (no auth wall);
  sessions index at /, individual session at /cockpit/<id>

The v0.5 CSR stub-login + AI-escalation case fixtures are gone; the
v1.0-baseline captures are limited to surfaces that work without
hand-seeded fixtures. Authenticated post-login self-serve dashboard
captures (the customer's line cards + the chat widget) require a
verified `bss_portal_session` cookie — left as a follow-up that
needs the seed-helper documented in CAPTURE.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parent
VIEWPORT = {"width": 1280, "height": 800}


def _resolve_chromium() -> str | None:
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if explicit and Path(explicit).is_file():
        return explicit
    cache = Path.home() / ".cache" / "ms-playwright"
    if not cache.is_dir():
        return None
    candidates = sorted(
        cache.glob("chromium-*/chrome-linux64/chrome"), reverse=True
    )
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _optimize(path: Path) -> None:
    if shutil.which("oxipng"):
        subprocess.run(["oxipng", "-o", "4", "--quiet", str(path)], check=False)
        print(f"  optimized: {path.name}")


# ── Public marketing surfaces ────────────────────────────────────────


def _welcome(page: Page) -> None:
    """Public landing — /welcome. Shows the brand bar + CTAs."""
    page.goto("http://localhost:9001/welcome")
    page.wait_for_selector(".page-title", timeout=10_000)
    page.wait_for_timeout(400)
    out = OUT / "portal_self_serve_welcome_v0_18.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


def _plans(page: Page) -> None:
    """Public plan picker — /plans. v0.17 added the Roaming row;
    PLAN_S shows '—' (alignment), PLAN_M shows '500 mb', PLAN_L
    shows '2 GB'."""
    page.goto("http://localhost:9001/plans")
    page.wait_for_selector(".plan-grid", timeout=10_000)
    page.wait_for_timeout(400)
    out = OUT / "portal_self_serve_plans_v0_18.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


# ── Cockpit (v0.13+) ─────────────────────────────────────────────────


def _cockpit_sessions_index(page: Page) -> None:
    """v0.13 cockpit landing — list of recent sessions, no login wall."""
    page.goto("http://localhost:9002/")
    page.wait_for_selector("body", timeout=10_000)
    page.wait_for_timeout(600)
    out = OUT / "portal_csr_cockpit_sessions_v0_18.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


def _cockpit_session_detail(page: Page) -> None:
    """v0.13 cockpit session view — opens the session with the MOST
    messages so the screenshot shows the agent transcript in action.

    Querying DB directly via the audit endpoint would be cleaner but
    requires the BSS_API_TOKEN; instead we scrape the sessions index
    for the highest "N messages" badge.
    """
    page.goto("http://localhost:9002/")
    page.wait_for_selector("body", timeout=10_000)
    # Each conversation card carries text like "13 messages" or
    # "(empty conversation)" / "0 messages". Prefer the row with the
    # highest visible message count — playwright JS handles the parse.
    href = page.evaluate(
        """() => {
            const links = Array.from(document.querySelectorAll('a[href^="/cockpit/SES-"]'));
            let best = null, bestCount = -1;
            for (const link of links) {
                const m = (link.textContent || "").match(/(\\d+)\\s*messages?/);
                const count = m ? parseInt(m[1], 10) : 0;
                if (count > bestCount) {
                    bestCount = count;
                    best = link.getAttribute("href");
                }
            }
            return best;
        }"""
    )
    if not href:
        print("  WARN: no cockpit sessions to capture; skipping detail")
        return
    page.goto(f"http://localhost:9002{href}")
    page.wait_for_selector("body", timeout=10_000)
    page.wait_for_timeout(600)
    out = OUT / "portal_csr_cockpit_session_v0_18.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


def main() -> int:
    with sync_playwright() as p:
        launch_kwargs: dict = {"headless": True}
        chromium_path = _resolve_chromium()
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
            print(f"using chromium: {chromium_path}")
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport=VIEWPORT, color_scheme="dark")
        page = ctx.new_page()

        for fn in (
            _welcome,
            _plans,
            _cockpit_sessions_index,
            _cockpit_session_detail,
        ):
            try:
                fn(page)
            except Exception as exc:
                print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
