# e2e reports

This directory holds the per-run artefacts from `make e2e` (v1.4+). The dir
itself is gitignored except for this README — actual reports are local-only.

## Layout (v1.4.1+)

Each invocation of `make e2e` creates a timestamped run directory containing
a **visual gallery** (`index.html`) plus a per-spec subdirectory of
screenshots, a Playwright trace zip, and a recorded video:

```
docs/e2e-reports/20260525T173800Z/
├── index.html                          ← open this in any browser
├── junit.xml                           ← JUnit XML for CI ingestion later
├── test-signup-golden-path-smoke/
│   ├── 01-signed-in.png
│   ├── 02-signup-form-blank.png
│   ├── 03-signup-form-filled.png
│   ├── 04-confirmation-with-esim-qr.png
│   ├── 05-dashboard-active-line.png
│   ├── trace.zip                       ← open: `playwright show-trace trace.zip`
│   └── video.webm                      ← drag into any browser
├── test-public-promo-applied-at-signup/
│   └── … (same shape)
└── … (8 more specs)
```

## What each artefact gives you

- **`index.html`** — the gallery. One section per spec, inline screenshot
  grid, link to the trace zip + an `<video>` element for the recording. No
  JS deps, self-contained. This is the primary review surface.
- **Per-step screenshots** (`NN-label.png`) — captured by `snap("label")`
  calls in each spec. Step number auto-increments so filesystem order
  matches narrative order. Click any screenshot in the gallery to open
  full-size in a new tab.
- **`trace.zip`** — Playwright's interactive trace recording. Captures DOM
  + network + console at every action. Open with:
  ```bash
  uv run --package bss-e2e playwright show-trace docs/e2e-reports/<ts>/<spec>/trace.zip
  ```
  Best tool for debugging a failed spec — you can scrub through every
  action, see DOM snapshots, network calls, console messages.
- **`video.webm`** — full browser recording of the spec's run. Drag into
  any browser or open with `vlc`. Best for demo / review.
- **`junit.xml`** — pytest's standard JUnit XML. Not visually useful, but
  small + parseable by CI tools (slot in for v1.4.x GH Actions later).

Timestamp format: `YYYYMMDDTHHMMSSZ` (UTC, ISO 8601 basic). Lexicographic
sort == chronological sort.

## Why not git-track?

- **Size** — a run with 10 specs is ~20 MB (videos + traces dominate).
  Repo bloat compounds.
- **Volatility** — every run produces a new directory. Diffs are pure
  noise.
- **Local-truth** — the report is a snapshot of *your* dev box's stack at
  *that* moment. CI artefacts (v1.4.x+) will live in GH Actions, not git.

## Pruning

Old runs are safe to delete — nothing else references them by path. A
sensible cleanup keeps the last 5 runs:

```bash
ls -1dt docs/e2e-reports/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf
```

## See also

- `phases/V1_4_0.md` — phase doc for the suite design.
- `docker-compose.e2e.yml` — provider overrides applied during a run.
- `packages/bss-e2e/` — the suite itself.
- `packages/bss-e2e/bss_e2e/report.py` — the gallery generator.
