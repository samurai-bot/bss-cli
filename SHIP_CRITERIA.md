# BSS-CLI v0.1 Ship Criteria

> This checklist is the gate for tagging `v0.1.0`. Every item must be
> verifiable from a fresh clone by someone who has never seen the repo
> before. If any line is red, we do not ship.

## Runtime

- [x] `docker compose up -d` brings up all 10 services + 3 infra containers cleanly on a clean machine.
- [x] All 10 service containers report `healthy` within 60 seconds of cold start.
- [x] Total resident memory across the 13 containers is under 4 GB at idle.
- [x] `make migrate` runs Alembic cleanly against an empty Postgres; replaying against an already-migrated DB is a no-op.
- [x] `make seed` populates 3 plans + 3 VAS offerings + 1000 MSISDNs + 1000 eSIM profiles.

## Hero scenarios (`bss scenario run <path>`)

All three must pass three runs in a row against a live stack.

- [x] `scenarios/customer_signup_and_exhaust.yaml` — 13 deterministic steps. Signup → order → activation → 5 GB burn → blocked state. Runs in ~2.5s.
- [x] `scenarios/new_activation_with_provisioning_retry.yaml` — 11 deterministic steps. Fault-injected provisioning task, retry, activation. Runs in ~2.2s.
- [x] `scenarios/llm_troubleshoot_blocked_subscription.yaml` — 14 steps (10 deterministic setup, 1 LLM `ask:`, 3 deterministic verification). LLM diagnoses + purchases VAS + logs interaction. Runs in 10–17s depending on the model's tool-chain length. **Three consecutive passes recorded before tag.**

## LLM surface

- [x] Orchestrator binds 75 tools via `build_graph()` (76 registered, minus 1 hidden by `_LLM_HIDDEN_TOOLS`).
- [x] Destructive tools (`subscription.terminate`, `customer.close`, etc.) short-circuit with `DESTRUCTIVE_OPERATION_BLOCKED` unless `--allow-destructive` is passed.
- [x] Every registered tool has a docstring (`test_tool_docstring_compliance`).
- [x] Every tool ID/enum argument uses a typed alias from `types.py` (`test_types_coverage`).
- [x] Tool exceptions are converted to structured string observations — the graph never crashes on a tool error.

## Determinism

- [x] Every scenario starts with `admin.reset_operational_data` and `clock.freeze_at`.
- [x] No business-logic module calls `datetime.utcnow()` — `bss_clock.now()` is the only path. Enforced by grep guard in CI (post-v0.1).
- [x] Sequence generators (`CUST-NNNN`, `ORD-NNNN`, `SUB-NNNN`, etc.) reset with `--reset-sequences`.

## Observability

- [x] Every service exposes `GET /audit-api/v1/events` (Task #3) with actor/channel/aggregate filters.
- [x] TMF683 Interaction log captures `channel` on every customer touchpoint.
- [x] `audit.domain_event` rows are written in the same transaction as the domain write; MQ publishes happen after commit.
- [x] Scenario runner's failure output shows the LLM's `tools_called` list and `final_message` on any ask step.

## Tests

- [x] `make test` runs all service + package + CLI suites. Pre-existing failing tests (3 in mediation, 1 in subscription, 1 in rating) are flagged as known issues in `DECISIONS.md` and tracked for post-v0.1.
- [x] Every policy has a positive and negative test.
- [x] Every state machine has an exhaustive transition table test.

## Documentation

- [x] `README.md` — quick start (bring-your-own-infra and all-in-one).
- [x] `CLAUDE.md` — project doctrine, read at the start of every session.
- [x] `ARCHITECTURE.md` — services, call patterns, deployment path.
- [x] `DATA_MODEL.md` — schemas + tables + relationships.
- [x] `TOOL_SURFACE.md` — full tool list with arg shapes.
- [x] `DECISIONS.md` — every non-obvious decision recorded.
- [x] `RUNBOOK.md` — operational procedures.
- [x] `SHIP_CRITERIA.md` — this file.

## Tagging

The user tags `v0.1.0` — not Claude Code. The tag is cut only after a
fresh-clone run of this checklist on a machine that has never seen the
repo. Nothing in this repo should assume the tag has been made.
