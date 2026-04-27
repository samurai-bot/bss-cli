# BSS-CLI Ship Criteria

> The gate for tagging a version. Every item must be verifiable from
> a fresh clone by someone who has never seen the repo before. If any
> line is red, we do not ship. **Numbers below are re-measured every
> minor version** — see `docs/runbooks/ship-criteria-remeasurement.md`
> for the recipe.

## Runtime — v0.6 (re-measured 2026-04-23, BYOI mode unless noted)

- [x] `docker compose up -d` brings up all **9 services + 2 portals** cleanly on a clean machine. (`docker compose -f docker-compose.yml -f docker-compose.infra.yml` adds Postgres + RabbitMQ + Metabase + Jaeger.)
- [x] All 11 BYOI containers report `healthy` within **~23 seconds** of cold start (motto target: <30s). Bundled-mode cold start adds ~12s for the 4 infra containers.
- [x] Total resident memory across the 11 BYOI containers is **~1.1 GB** at idle (motto target: <4 GB). Bundled adds Postgres ~400 MB + RabbitMQ ~350 MB + Metabase ~600 MB + Jaeger ~200 MB → **~2.65 GB total bundled** (still under 4 GB).
- [x] `make migrate` runs Alembic cleanly against an empty Postgres; replaying against an already-migrated DB is a no-op.
- [x] `make seed` populates 3 plans + 3 VAS offerings + 1000 MSISDNs + 1000 eSIM profiles.

### v0.1 numbers (retained for diff reference)

- 10 service containers + 3 infra → ~2.85 GB bundled / ~1.5 GB BYOI.
- v0.6 numbers are *better than* v0.1 BYOI (one fewer service: billing deferred; OTel + portals net out lower) and slightly better than v0.1 bundled (Jaeger added; tighter Python images).

## Hero scenarios (`bss scenario run <path>`)

**All six** must pass three runs in a row against a live stack. v0.6 ships with all 6 green.

- [x] `scenarios/customer_signup_and_exhaust.yaml` — v0.1 — 13 deterministic steps. ~2.7s.
- [x] `scenarios/new_activation_with_provisioning_retry.yaml` — v0.1 — 11 deterministic steps. ~2.2s.
- [x] `scenarios/llm_troubleshoot_blocked_subscription.yaml` — v0.1 — 14 steps; LLM-driven. **15-30s (model variance).** Three-runs-in-a-row gate.
- [x] `scenarios/trace_customer_signup_swimlane.yaml` — v0.2 — 6 steps; OTel trace span fan-out assertion. ~3.3s.
- [x] `scenarios/portal_self_serve_signup.yaml` — v0.4 — 11 steps; portal HTTP surface drives the agent end-to-end. **15-25s (model variance).** Three-runs-in-a-row gate.
- [x] `scenarios/portal_csr_blocked_diagnosis.yaml` — v0.5 — 16 steps; CSR operator asks the LLM to fix a blocked subscription. **15-30s (model variance).** Three-runs-in-a-row gate.

## LLM surface

- [x] Orchestrator binds 75 tools via `build_graph()` (76 registered, minus 1 hidden by `_LLM_HIDDEN_TOOLS`).
- [x] Destructive tools (`subscription.terminate`, `customer.close`, etc.) short-circuit with `DESTRUCTIVE_OPERATION_BLOCKED` unless `--allow-destructive` is passed.
- [x] Every registered tool has a docstring (`test_tool_docstring_compliance`).
- [x] Every tool ID/enum argument uses a typed alias from `types.py` (`test_types_coverage`).
- [x] Tool exceptions are converted to structured string observations — the graph never crashes on a tool error.

## Determinism

- [x] Every scenario starts with `admin.reset_operational_data` and `clock.freeze_at`.
- [x] No business-logic module calls `datetime.utcnow()` — `bss_clock.now()` is the only path. **Enforced by `make doctrine-check` grep guard in CI (added v0.6).**
- [x] Sequence generators (`CUST-NNNN`, `ORD-NNNN`, `SUB-NNNN`, etc.) reset with `--reset-sequences`.

## Observability

- [x] Every service exposes `GET /audit-api/v1/events` (Task #3) with actor/channel/aggregate filters.
- [x] TMF683 Interaction log captures `channel` on every customer touchpoint.
- [x] `audit.domain_event` rows are written in the same transaction as the domain write; MQ publishes happen after commit.
- [x] Scenario runner's failure output shows the LLM's `tools_called` list and `final_message` on any ask step.

## Tests — v0.6 status

- [x] `make test` runs all service + package + CLI + portal suites. **805 tests, 0 failures, 0 errors** (was: 793 in pre-v0.6 baseline; v0.6 added 12 renderer-snapshot tests in PR 2).
- [x] Every policy has a positive and negative test.
- [x] Every state machine has an exhaustive transition table test.
- [x] **The 5 pre-v0.1 known-failing tests** flagged in the v0.1 SHIP_CRITERIA (3 mediation, 1 subscription, 1 rating) **are no longer failing** — current suite counts are mediation 42/42, subscription 96/96, rating 29/29. They were greened or retired in pre-tag work that wasn't recorded; v0.6 retroactively confirms them gone.
- [x] **Renderer snapshot tests** (`UPDATE_SNAPSHOTS=1` workflow) cover 5 hero ASCII renderers — see `docs/runbooks/snapshot-regeneration.md`.

## Doctrine guards — v0.6 added `make doctrine-check`

- [x] `make doctrine-check` enforces the four grep guards as a single CI-runnable target:
  - `datetime.now/utcnow` only allowed in `bss-clock` impl, the `bss clock` cmd surface, tests, and explicitly `# noqa: bss-clock`-annotated lines.
  - Portal route handlers on the chat surface must not call mutating `bss-clients` methods (chat writes go through the orchestrator). v0.10+ post-login self-serve routes and v0.11+ signup routes are explicit carve-outs that may write directly via `bss-clients`; the doctrine guard maintains an allowlist for them.
  - OTel SDK imports must not leak into `services/*/app/services/` or `services/*/app/policies/`.
  - The string `campaignos` must not appear in code (alembic migrations excepted — they reference it in comments to document what we *don't* touch).

## Documentation — v0.6 final

- [x] `README.md` — 9-section structure with portal screenshots inline (rewritten v0.6).
- [x] `CLAUDE.md` — project doctrine, read at the start of every session. Drift-fix updates v0.6.
- [x] `ARCHITECTURE.md` — services, call patterns, deployment path. Topology + portals + footprint refreshed v0.6.
- [x] `DATA_MODEL.md` — schemas + tables + relationships.
- [x] `TOOL_SURFACE.md` — every registered tool documented; planned/admin/non-tool entries tagged with status badges (v0.6).
- [x] `DECISIONS.md` — every non-obvious decision recorded.
- [x] `CONTRIBUTING.md` — phase discipline, DECISIONS pattern, test conventions, "how to add a new service" (new v0.6).
- [x] `ROADMAP.md` — shipped + near-term + Phase 12 + speculative + non-goals (new v0.6).
- [x] `docs/runbooks/snapshot-regeneration.md` — UPDATE_SNAPSHOTS=1 workflow (new v0.6).
- [x] `docs/runbooks/ship-criteria-remeasurement.md` — exact recipe for the numbers above (new v0.6).
- [x] `docs/runbooks/jaeger-byoi.md` — current.
- [x] `docs/runbooks/api-token-rotation.md` — current.
- [x] `docs/runbooks/phase-execution-runbook.md` — phase build workflow.
- [x] `docs/screenshots/` — 5 committed PNGs (`bss_trace_swimlane_v0_2`, portal self-serve signup + confirmation v0.4, portal CSR 360 + agent mid-stream v0.5).
- [x] `SHIP_CRITERIA.md` — this file.

## Tagging

The user tags the version — not Claude Code. The tag is cut only after a
fresh-clone run of this checklist on a machine that has never seen the
repo. Nothing in this repo should assume the tag has been made.
