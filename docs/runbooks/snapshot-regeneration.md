# Regenerating renderer snapshots

> Some CLI renderers — subscription show, customer 360, order tree, catalog comparison, eSIM card — are pinned by golden-file snapshot tests. When you intentionally change a renderer's output, the corresponding `.txt` file under `cli/tests/snapshots/` (or per-version `cli/tests/v0_X_0/snapshots/`) must be regenerated and committed in the same PR as the code change.

## When to regenerate

Only after a deliberate visual change. Snapshots are review artifacts — the diff between the old and new golden file is what a reviewer reads to confirm the polish landed correctly.

**Don't auto-regenerate in CI.** A CI-side auto-regen masks unintended drift; manual regeneration with code-review-of-the-diff is the gate.

## How to regenerate

```bash
# From repo root
UPDATE_SNAPSHOTS=1 uv run pytest cli/tests/test_renderer_*.py -v

# Inspect what changed
git diff cli/tests/snapshots/ cli/tests/v0_*/snapshots/

# If the diff is what you intended, stage it with the renderer change
git add cli/bss_cli/renderers/<file>.py cli/tests/snapshots/
git commit -m "feat(vX.Y.Z): polish <renderer> — <one-line summary>"
```

The `assert_snapshot(name, actual)` helper in `cli/tests/conftest.py` reads the golden file under `cli/tests/snapshots/<name>.txt` (or the per-version directory specified at the call site), compares against `actual`, and on mismatch prints both versions side-by-side. Under `UPDATE_SNAPSHOTS=1`, it writes `actual` to the golden file instead.

## Common pitfalls

- **Trailing whitespace.** ASCII tables sometimes pick up trailing spaces from `ljust` calls. The snapshot comparison is byte-exact; a trailing-space diff means the renderer's column padding changed. Either fix the renderer to right-strip rows, or accept the new shape and commit.
- **Locale-dependent number formatting.** `f"{value:g}"` collapses trailing zeros (`5.0` → `5`); `f"{value:.2f}"` doesn't. Pick one and stay consistent across the renderer.
- **Time-dependent fields.** Snapshots that include "now"-relative durations (e.g. `2h 15m ago`) need a clock-frozen test harness or a `# noqa: snapshot-volatile` comment near the field. Don't use real `datetime.now()` in a snapshot test.

## v0.6 reference

The five hero renderers polished in v0.6 each updated their golden files in the PR-2 commit:
- `cli/tests/snapshots/subscription_show_active.txt` + `_blocked.txt`
- `cli/tests/snapshots/customer_show_active.txt` + variants
- `cli/tests/snapshots/order_show_*.txt`
- `cli/tests/snapshots/catalog_list_compact.txt` + `catalog_show_plan_m.txt`
- `cli/tests/snapshots/esim_*.txt`

If a future polish session edits any of these renderers, regenerate the corresponding snapshot via the workflow above and commit the diff alongside the code change.
