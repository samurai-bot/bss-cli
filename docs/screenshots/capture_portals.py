#!/usr/bin/env python3
"""Capture v0.6 portal screenshots via playwright headless.

Run from repo root:
    uv run python docs/screenshots/capture_portals.py

Prereqs (see CAPTURE.md):
    uv pip install playwright
    uv run python -m playwright install chromium

The script assumes:
    - portal-self-serve healthy on http://localhost:9001
    - portal-csr healthy on http://localhost:9002
    - DB reset and seeded so customer fixture names match
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parent
VIEWPORT = {"width": 1280, "height": 800}


def _resolve_chromium() -> str | None:
    """If ``playwright install chromium`` failed for this OS (e.g.
    Ubuntu 26.04 isn't on the supported list), fall back to an
    already-cached chromium under ``~/.cache/ms-playwright``.
    Set ``PLAYWRIGHT_CHROMIUM_EXECUTABLE`` to override. Returns
    ``None`` to let playwright pick its bundled default."""
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


def _self_serve_signup(page: Page) -> None:
    """v0.12 — capture the direct-write signup form + confirmation.

    Pre-condition (see CAPTURE.md): the page's Context carries a
    verified-but-unlinked ``bss_portal_session`` cookie so the
    /signup/* routes pass ``requires_verified_email``. The linked
    identity carries the customer's email; the form is minimal
    (name + phone + card_pan; KYC pre-baked, msisdn pre-picked).
    """
    page.goto("http://localhost:9001/signup/PLAN_M?msisdn=90000000")
    page.wait_for_selector("button.form-submit", timeout=10_000)
    page.fill('input[name="name"]', "Ck Demo")
    page.fill('input[name="phone"]', "+6590001234")
    page.wait_for_timeout(400)
    out = OUT / "portal_self_serve_signup_v0_12.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)
    page.click("button.form-submit")
    try:
        page.wait_for_url("**/confirmation/*", timeout=60_000)
        page.wait_for_timeout(800)
        out2 = OUT / "portal_self_serve_confirmation_v0_12.png"
        page.screenshot(path=str(out2), full_page=False)
        print(f"captured: {out2.name}")
        _optimize(out2)
    except Exception as exc:
        print(f"  WARN: confirmation capture skipped — {exc}")


def _csr_360_and_ask(page: Page) -> None:
    """Login, find a customer with a blocked subscription, capture 360 + ask."""
    # Stub login
    page.goto("http://localhost:9002/login")
    page.fill('input[name="username"]', "csr-demo-001")
    page.fill('input[name="password"]', "anything")
    page.click('button[type="submit"]')
    page.wait_for_url("**/search", timeout=10_000)

    # Find a customer — search by 'Demo' which matches scenario fixtures.
    page.fill('form.search-form input[name="q"]', "Demo")
    page.locator('form.search-form button').click()
    # First result row link
    page.wait_for_selector('table.search-results', timeout=10_000)
    first = page.locator('table.search-results tbody tr a').first
    first.click()
    page.wait_for_url("**/customer/CUST-*", timeout=10_000)
    page.wait_for_timeout(800)

    out = OUT / "portal_csr_360_v0_5.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)

    # Submit an ask — capture mid-stream
    page.fill(
        'form.ask-form input[name="question"]',
        "Why is their data not working? Fix it if you can.",
    )
    page.click('form.ask-form button[type="submit"]')
    page.wait_for_url("**/customer/CUST-*?session=*", timeout=10_000)
    # Pause long enough for several agent events to land but before final
    page.wait_for_timeout(8_000)
    out2 = OUT / "portal_csr_agent_midstream_v0_5.png"
    page.screenshot(path=str(out2), full_page=False)
    print(f"captured: {out2.name}")
    _optimize(out2)


def _self_serve_dashboard_with_fab(page: Page) -> None:
    """v0.12 — dashboard with the floating "Chat with us" pill visible
    bottom-right. Requires the customer to be logged in via portal_auth.
    Use a freshly-seeded test session (see CAPTURE.md) so the
    dashboard renders one or more line cards.
    """
    page.goto("http://localhost:9001/")
    page.wait_for_selector(".chat-fab", timeout=10_000)
    page.wait_for_timeout(400)
    out = OUT / "portal_self_serve_dashboard_v0_12.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


def _self_serve_chat_widget(page: Page) -> None:
    """v0.12 — chat widget popup open over the dashboard, with a
    short conversation: one user question + the assistant's reply.
    Drives a real LLM round-trip so the bubble content is realistic;
    waits for the SSE 'done' status before snapshotting."""
    page.goto("http://localhost:9001/")
    page.wait_for_selector(".chat-fab", timeout=10_000)
    page.click(".chat-fab")
    page.wait_for_selector(".chat-widget-popup", timeout=5_000)
    page.fill(
        '.chat-widget-form textarea[name="message"]',
        "what plans do you have?",
    )
    page.click('.chat-widget-form button[type="submit"]')
    # Wait for status: done — the SSE stream finishes when the
    # streaming bubble's status pill swaps to ``dot done``.
    page.wait_for_selector(".chat-status .dot.done", timeout=30_000)
    page.wait_for_timeout(600)
    out = OUT / "portal_self_serve_chat_widget_v0_12.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"captured: {out.name}")
    _optimize(out)


def _csr_case_with_transcript(page: Page) -> None:
    """v0.12 — CSR's case detail page rendering the chat-transcript
    panel for an AI-opened escalation case. Pre-condition: at least
    one case exists with chat_transcript_hash set (run the
    portal_chat_escalation_to_case hero scenario before capturing)."""
    page.goto("http://localhost:9002/login")
    page.fill('input[name="username"]', "csr-demo-001")
    page.fill('input[name="password"]', "anything")
    page.click('button[type="submit"]')
    page.wait_for_url("**/search", timeout=10_000)
    # Find the customer who has the AI-escalated case.
    page.fill('form.search-form input[name="q"]', "Escalation")
    page.locator('form.search-form button').click()
    page.wait_for_selector('table.search-results', timeout=10_000)
    page.locator('table.search-results tbody tr a').first.click()
    page.wait_for_url("**/customer/CUST-*", timeout=10_000)
    # Click the first AI-escalated case in the cases panel.
    case_link = page.locator('a[href^="/case/CASE-"]').first
    case_link.click()
    page.wait_for_url("**/case/CASE-*", timeout=10_000)
    page.wait_for_selector(".chat-transcript-section", timeout=5_000)
    page.wait_for_timeout(400)
    out = OUT / "portal_csr_case_transcript_v0_12.png"
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

        try:
            _self_serve_signup(page)
        except Exception as exc:
            print(f"FAIL self-serve signup: {exc}", file=sys.stderr)

        try:
            _csr_360_and_ask(page)
        except Exception as exc:
            print(f"FAIL csr ask: {exc}", file=sys.stderr)

        # v0.12 — chat surface captures. These need a session cookie
        # already present (see CAPTURE.md for the seed-helper pattern).
        try:
            _self_serve_dashboard_with_fab(page)
        except Exception as exc:
            print(f"FAIL self-serve dashboard fab: {exc}", file=sys.stderr)

        try:
            _self_serve_chat_widget(page)
        except Exception as exc:
            print(f"FAIL self-serve chat widget: {exc}", file=sys.stderr)

        try:
            _csr_case_with_transcript(page)
        except Exception as exc:
            print(f"FAIL csr case transcript: {exc}", file=sys.stderr)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
