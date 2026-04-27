# Capturing screenshots for `docs/screenshots/`

> v0.6 introduced `docs/screenshots/` as the canonical home for committed PNGs that the README references. This file documents how each one is captured so a future maintainer can re-do them cleanly. Naming convention: `<feature>_v0_X.png`. All captures use a freshly-reset operational DB so fixture names match (`Ck Demo`, `portal-demo-*`, `csr-demo-*`).

## Prerequisites

```bash
# Reset DB so fixture names line up
uv run bss admin reset-operational-data
make seed

# Bring everything up
docker compose up -d --wait

# Dev-only deps for capture (not installed by default)
uv pip install playwright
uv run python -m playwright install chromium
# Terminal captures: install scrot or maim on the host (apt install scrot)
```

## Portal screenshots (playwright, headless)

Run `python docs/screenshots/capture_portals.py` from the repo root. The script drives each portal with playwright headless, captures at 1280×800, writes PNGs into `docs/screenshots/`, and optimizes via `oxipng -o 4` if available.

Captures produced:

- `portal_self_serve_signup_v0_12.png` *(replaces the deleted v0_4 capture)* — direct-write signup form (linked-identity flow): minimal fields (name + phone + card pre-fill + pre-baked KYC). The capture context carries a verified-but-unlinked session cookie so `requires_verified_email` passes; without that, /signup/* redirects to login.
- `portal_self_serve_confirmation_v0_12.png` *(replaces the deleted v0_4 capture)* — confirmation page with eSIM QR PNG. Continues from the signup capture's redirect.
- `portal_csr_360_v0_5.png` — customer 360 view with a blocked subscription highlighted. Pre-blocks SUB-0001 via `usage.simulate` so the state shows.
- `portal_csr_agent_midstream_v0_5.png` — operator's ask form submitted, agent log mid-stream. Snapshots the agent log between `tool_started` and `tool_completed` for a visible streaming state.
- `portal_self_serve_dashboard_v0_12.png` — dashboard with the floating "Chat with us" pill bottom-right.
- `portal_self_serve_chat_widget_v0_12.png` — chat popup widget opened over the dashboard, one full conversation turn rendered.
- `portal_csr_case_transcript_v0_12.png` — CSR case-detail page showing the "Chat transcript" panel for an AI-opened escalation case.

The v0.12 dashboard / chat-widget captures need a verified linked-customer session in `portal_auth.session` before they run; the v0.12 signup capture needs an unlinked-but-verified session (no customer_id yet). Both are easiest to seed via `bss_portal_auth.test_helpers.create_test_session`. The CSR transcript capture additionally needs at least one case with `chat_transcript_hash` set — run the `portal_chat_escalation_to_case` hero scenario before capturing. The `bss_trace_swimlane_v0_2.png` was re-cropped at v0.12 (1280×1200, top-half of the original ~2200px capture) to keep the README scroll length sensible.

## Terminal screenshots (manual — needs a display)

These two need a real terminal session:

- `bss_trace_swimlane_v0_2.png` — output of `bss trace for-order ORD-0001` after running `customer_signup_and_exhaust`.
- `bss_repl_ask_v0_1.png` *(optional)* — output of `bss ask "Show me the most recent customer."`.

Capture procedure on the host:

```bash
# 120-column dark-theme terminal
resize -s 40 120     # if using xterm; alacritty/kitty have similar
# Run the command, then capture the visible terminal area
scrot -s docs/screenshots/bss_trace_swimlane_v0_2.png   # interactive selection
oxipng -o 4 docs/screenshots/bss_trace_swimlane_v0_2.png
```

Aim for **<300 KB per PNG** post-`oxipng`. Strip URL bars (browser captures) by feeding playwright the `viewport_size` only — see the script.

## Discipline

- **No real customer data.** Every capture uses scenario-fixture names (`Ck Demo`, `portal-demo-{run_id}`, `csr-demo-001`).
- **Dark theme only.** Light theme captures are out of scope for v0.6.
- **Deterministic state.** Always reset DB first; never capture against a long-running stack with accumulated state.
- **Commit the PNGs.** `docs/screenshots/*.png` are part of the repo, not external links. README references them via relative paths.
