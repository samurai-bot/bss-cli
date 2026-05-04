# Capturing screenshots for `docs/screenshots/`

> v0.18 baseline. The committed PNGs are what the README links to.
> Naming convention: `<surface>_v0_X.png`. Re-capture when the
> rendered surface meaningfully changes (banner, layout, brand
> elements, version stamp).

## Web surfaces (Playwright)

```bash
# Bring the stack up
docker compose up -d --wait

# Dev-only deps (not in the workspace lock)
uv pip install playwright
uv run python -m playwright install chromium

# Capture
uv run python docs/screenshots/capture_portals.py
```

The script captures four surfaces and writes them next to itself:

| File | URL | Notes |
|---|---|---|
| `portal_self_serve_welcome_v0_18.png` | `localhost:9001/welcome` | Public landing — brand bar + Sign in / Browse plans CTAs |
| `portal_self_serve_plans_v0_18.png` | `localhost:9001/plans` | Three-card plan picker; v0.17 Roaming row visible (PLAN_S "—", PLAN_M 500 mb, PLAN_L 2 GB) |
| `portal_csr_cockpit_sessions_v0_18.png` | `localhost:9002/` | Cockpit sessions index — "Hello, operator", recent conversations |
| `portal_csr_cockpit_session_v0_18.png` | `localhost:9002/cockpit/SES-...` | Live cockpit conversation — chosen at runtime as the session with the most messages |

Re-run any time the running stack reflects the surface you want.
The captures use a 1280×800 viewport, dark color scheme, headless
chromium from `~/.cache/ms-playwright` (override via
`PLAYWRIGHT_CHROMIUM_EXECUTABLE`).

## Trace swimlane (terminal `bss trace`)

```bash
uv run python docs/screenshots/capture_trace.py
```

Produces `bss_trace_swimlane_v0_2.png`. Hasn't changed since v0.2;
re-capture if the renderer meaningfully evolves.

## Terminal REPL banner (`bss_repl_v0_19.jpg`)

The Rich-rendered REPL banner can't be captured by Playwright (no
DOM) and headless terminal capture loses the ANSI rendering. Capture
this manually:

1. Open a wide terminal (~2000×1300 px — ghostty / kitty / iterm2 /
   alacritty all work).
2. `uv run bss`.
3. Run a few representative queries so the banner sits above real
   conversation output:
   ```
   list all products
   how about the VASes?
   show me more details about PLAN_L please
   ```
4. Take a window screenshot and save as
   `docs/screenshots/bss_repl_v0_19.jpg` (PNG also fine — terminals
   produce either; the v0.19 capture is JPEG @ 3200×2092 ~510 KB
   which renders crisply on github.com).

The README links this filename verbatim; commit at the same path.

## Discipline

- **No real customer data.** Captures use scenario-fixture names
  (`Trace Demo` / `Ck Demo` / `portal-demo-*`).
- **Dark theme only.**
- **Commit the PNGs.** `docs/screenshots/*.png` are part of the repo,
  not external links.
- **Optimize.** If `oxipng` is on PATH, the capture script runs
  `oxipng -o 4` automatically; install it for a 30-50% size win
  (`apt install oxipng`).
