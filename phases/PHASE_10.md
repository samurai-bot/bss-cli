# Phase 10 — Scenario Runner + Hero Scenarios

> **The shipping phase.** When this is green, v0.1 is done. Resist scope creep. Ship when the checklist is checked.
>
> **This is also the phase where we prove the LLM actually works end-to-end.** Phase 9 built the semantic layer and wired the LLM path; Phase 10 proves it by running hero scenarios through the real model against real services. If Phase 10 only tests the tool path and skips the LLM path, v0.1 is a BSS with an LLM demo bolted on, not an LLM-native BSS. Do not skip LLM-mode scenarios.

## Goal

A YAML scenario runner with **two execution modes** (deterministic tool-call and LLM-driven), plus three hero scenarios that prove the system works end-to-end. Plus a `bss admin reset` command for manual "back to clean state" outside of scenario runs. These scenarios are the seed mechanism for demo data, the regression test suite, and the thing you'll show on LinkedIn post-v0.2.

## Deliverables

### 0. Pre-work (before scenario runner implementation)

Two small items that must land before the scenario runner is wired, because the runner depends on them:

#### 0a. `admin.reset_operational_data` endpoint

The admin service (or a new `admin-api` sub-domain on an existing service — Claude Code decides the cleanest home) exposes `POST /admin-api/v1/reset-operational-data`. Behavior:

- Truncates every operational table across all BSS schemas (customers, contact mediums, KYC attestations, cases, tickets, notes, interactions, payment methods, payment attempts, product orders, service orders, services, provisioning tasks, subscriptions, bundle balances, VAS purchases, usage events, bills, `audit.domain_event` rows)
- Resets MSISDN pool entries to `status='available'` (any assigned MSISDNs are released back to the pool)
- Resets eSIM profile pool entries to `profile_state='available'` (any reserved/assigned profiles are released back to the pool)
- **Does NOT touch reference data** — catalog, product offerings, service specifications, product-to-service mapping, agents, SLA policies, tariffs, fault injection rules, MSISDN pool entries' `msisdn` column (just the `status`), eSIM profile pool entries' `iccid` column (just the `profile_state`)
- **Does NOT touch the `campaignos` schema.** The endpoint has an explicit schema allowlist; any code path that would touch a non-BSS schema fails loudly.
- **Does NOT reset sequences** by default. IDs continue where they left off. Optional `?reset_sequences=true` query parameter for fresh-start runs where ID monotonicity across runs matters (e.g. snapshot tests).
- Returns a summary: `{"truncated_tables": [...], "msisdn_pool_reset": N, "esim_pool_reset": M, "campaignos_touched": false}`
- Idempotent. Safe to call repeatedly.

**Policy-gated** — this is destructive and only allowed when `BSS_ALLOW_ADMIN_RESET=true` is set in `.env`. Default is `false`. Production deployments never set this.

#### 0b. `bss admin reset` CLI command

A top-level CLI command that calls the endpoint above. UX:

```bash
$ bss admin reset
⚠ This will wipe all operational data (customers, orders, subscriptions,
  cases, tickets, payments, usage, bills) and reset the MSISDN and eSIM
  pools to their seed state.

  Reference data (catalog, agents, SLA policies, fault rules) is preserved.
  Campaign OS schemas are never touched.

  Type 'reset' to confirm, or anything else to cancel: _

$ bss admin reset --yes              # skip confirmation, scriptable
$ bss admin reset --reset-sequences  # also reset ID sequences (fresh monotonic IDs)
```

Implementation:

- Lives in `cli/bss_cli/commands/admin.py` alongside other admin commands
- Uses the same `bss-clients` pattern as other CLI commands (no direct HTTP)
- Reads `BSS_ALLOW_ADMIN_RESET` from the CLI's own `.env` to give a helpful error if the flag is off
- Renders the summary from the endpoint as a small ASCII table: "Customers wiped: N. Orders wiped: M. MSISDNs released: K." etc.
- Logs the action as an interaction with `X-BSS-Actor: cli-user`, `X-BSS-Channel: cli` — the reset itself is audit-visible

**Why this matters:** during REPL exploration post-v0.1, users will create customers, orders, subscriptions, and want to reset without running a full scenario. `bss admin reset` is the explicit manual path. Scenario runner still uses the same underlying endpoint via `setup.reset_operational_data: true` — same code, same guarantees, two invocation paths.

**Pre-work verification** (must pass before scenario runner work starts):

- [ ] `POST /admin-api/v1/reset-operational-data` exists and works against a dirty DB
- [ ] `bsspsql -c "SELECT COUNT(*) FROM campaignos.<any_table>"` returns the same count before and after a reset
- [ ] `bsspsql -c "SELECT COUNT(*) FROM catalog.product_offering"` returns the same count before and after a reset (reference data preserved)
- [ ] `bsspsql -c "SELECT COUNT(*) FROM crm.customer"` returns 0 after a reset (operational data wiped)
- [ ] `BSS_ALLOW_ADMIN_RESET=false` → endpoint returns 403
- [ ] `bss admin reset` without `--yes` prompts for confirmation
- [ ] `bss admin reset --yes` runs without prompting
- [ ] `bss admin reset` fails cleanly with helpful error when `BSS_ALLOW_ADMIN_RESET=false`
- [ ] `audit.domain_event` shows the reset action with actor `cli-user` and channel `cli`

These go into a **separate chore commit on main before the scenario runner branch is cut**. Tag the commit `chore: admin.reset_operational_data endpoint + bss admin reset CLI` — no phase-10 tag yet, that comes at the end.

### 1. Scenario runner — `cli/bss_cli/scenarios/`

```
cli/bss_cli/scenarios/
├── __init__.py
├── runner.py           # main loop — deterministic and LLM modes
├── schema.py           # pydantic models for YAML
├── actions.py          # action registry (maps action name → tool call)
├── assertions.py       # assertion evaluator with polling
├── context.py          # variable interpolation + captured values
├── llm_executor.py     # LLM-mode step executor — routes natural language through orchestrator
└── reporting.py        # pass/fail rendering
```

Invoked via:

```
bss scenario run scenarios/customer_signup_and_exhaust.yaml
bss scenario run scenarios/new_activation_with_provisioning_retry.yaml
bss scenario run scenarios/llm_troubleshoot_blocked_subscription.yaml
bss scenario list
bss scenario validate scenarios/*.yaml

# Force deterministic mode (override ask: steps to fail)
bss scenario run scenarios/foo.yaml --no-llm

# Force LLM mode (convert action: steps to natural language if the scenario supports it)
bss scenario run scenarios/foo.yaml --via-llm
```

### 2. Execution modes — deterministic and LLM

Phase 10 defines **two scenario execution modes**, with per-step granularity.

**Deterministic mode** — the default for most steps. A step with an `action:` field invokes an orchestrator tool directly as a Python function call. Fast (~10ms per step), reliable, zero LLM cost, reproducible across runs. This is the regression test suite — it exercises services, the event chain, the policy layer, and the renderers, but bypasses the LLM.

**LLM mode** — for steps that prove the LLM works. A step with an `ask:` field passes natural-language instructions through the real OpenRouter-backed LangGraph orchestrator. The LLM plans, calls tools, handles errors, and either completes the instruction or reports why it can't. Slower (~2-10s per step depending on tool chain length), costs real money (under a cent per scenario run with MiMo), requires OpenRouter to be reachable.

**Per-step mode selection:**

```yaml
steps:
  # Deterministic step — direct tool call, no LLM
  - name: create customer
    action: customer.create
    args:
      name: "Ck Demo"
      email: "ck@bss-cli.local"
    capture:
      customer_id: "$.id"

  # LLM step — natural language through real LLM
  - name: diagnose the blocked subscription
    ask: "The customer {{ customer_id }} says their data stopped working. Figure out why and fix it if possible."
    expect_tools_called_include:
      - subscription.get
      - subscription.get_balance
      - catalog.list_vas
      - subscription.purchase_vas
    expect_final_state:
      subscription_id: "{{ subscription_id }}"
      state: active
```

A scenario can mix both styles. Setup and teardown are typically deterministic (for reproducibility); the core value-adding steps can be LLM-driven to prove the agent's reasoning.

**Why not always-LLM:** LLM calls are slightly non-deterministic even on cheap models. Forcing every setup step through the LLM means a 10-second scenario becomes a 90-second scenario for no test-value gain. The hybrid model keeps setup fast and reproducible while proving the interesting parts through the real agent.

**Why not always-deterministic:** a scenario that only calls tools directly never exercises the LLM. If the LLM path breaks — bad docstring, wrong tool schema, fabrication in the supervisor loop — deterministic-only scenarios won't catch it. You'd ship a broken agent with a green test suite.

**Mode flags:**

- Default: each step runs in its declared mode (`action:` → deterministic, `ask:` → LLM).
- `--no-llm`: every `ask:` step fails immediately with a clear error. Useful for fast iteration in CI where you don't want OpenRouter in the loop.
- `--via-llm`: every `action:` step is converted into a natural-language `ask:` equivalent at runtime. **Experimental** — some actions don't translate cleanly (e.g., `admin.reset_operational_data` has no natural phrasing). Use only on scenarios that were designed with this in mind.

### 3. Scenario YAML schema

```yaml
name: customer_signup_and_exhaust
description: |
  Creates a customer, attaches COF, orders PLAN_S, simulates usage to exhaustion,
  verifies blocking, tops up via VAS, verifies unblocking.
tags: [hero, smoke, regression, deterministic]

setup:
  reset_operational_data: true      # calls POST /admin-api/v1/reset-operational-data
  freeze_clock_at: "2026-04-11T09:00:00+08:00"

variables:
  customer_name: "Ck Demo"
  customer_email: "ck-{{ run_id }}@bss-cli.local"
  plan: PLAN_S

steps:
  - name: create customer
    action: customer.create
    args:
      name: "{{ customer_name }}"
      email: "{{ customer_email }}"
      phone: "+6590001234"
    capture:
      customer_id: "$.id"

  # (rest of the scenario as deterministic action: steps)

teardown:
  unfreeze_clock: true
```

**Step types:**

- `action:` — direct tool call (deterministic mode). Args are structured.
- `ask:` — natural-language instruction (LLM mode). Single string, may use `{{ variable }}` interpolation.
- `assert:` — tool call with expected result shape. Polling optional.

**LLM step fields:**

```yaml
- name: diagnose and fix
  ask: "Ck's subscription {{ subscription_id }} is blocked. Figure out why and fix it."

  # What tools the LLM MUST call at least once. Test fails if any are missing.
  expect_tools_called_include:
    - subscription.get
    - subscription.get_balance
    - subscription.purchase_vas

  # What tools the LLM MUST NOT call. Test fails if any are called.
  expect_tools_not_called:
    - subscription.terminate
    - customer.close

  # The final state of some resource after the LLM finishes. Test fails if wrong.
  expect_final_state:
    subscription_id: "{{ subscription_id }}"
    state: active

  # Max wall-clock seconds for the LLM to finish. Default 60.
  timeout_seconds: 60

  # Optional: require the LLM to have emitted a specific event sequence
  expect_event_sequence:
    - subscription.vas_purchased
    - subscription.unblocked

  # Optional: allow the LLM to ask clarifying questions (default false — strict mode)
  allow_clarification: false
```

**Why `expect_tools_called_include` instead of exact match:** the LLM may legitimately call extra read tools (e.g., `customer.get` to verify) that a hand-crafted scenario didn't anticipate. Exact match would be too brittle. Include-mode asserts "at minimum, these tools ran" without forbidding reasonable exploration.

**Why `expect_final_state`:** the most important check isn't "did the LLM call the right tools" — it's "is the system in the right state when the LLM finished." A good LLM might take a different path to the same correct result. Assert the result, not the path, unless the path itself is what you're testing.

### 4. Runner mechanics

- **Variable interpolation:** Jinja-style `{{ var }}`, substituted at step evaluation time. Captures from earlier steps are in scope.
- **Capture:** JSONPath expressions via `jsonpath-ng` pull values from tool results into the variable context.
- **Assertions:** dot-path field checks against tool results. Polling (`poll.interval_ms`, `poll.timeout_seconds`) for async-settling state.
- **LLM step execution:** `llm_executor.py` constructs the LangGraph orchestrator with the real OpenRouter client, injects the current variable context as system context, passes the `ask:` string, runs the graph to completion, captures tool-call trace and final state.
- **Reset:** `setup.reset_operational_data: true` → calls the same `POST /admin-api/v1/reset-operational-data` endpoint that `bss admin reset` uses. One code path, two invocation sites.
- **Clock freeze:** `clock.freeze` propagates to every service. `teardown.unfreeze_clock` restores.
- **Channel injection:** runner sets `X-BSS-Channel: scenario` and `X-BSS-Actor: scenario:<n>` for deterministic steps; LLM steps use `X-BSS-Channel: llm`, `X-BSS-Actor: llm-<model-slug>`. Both paths auto-log to CRM interactions.
- **Reporting:** structured pass/fail per step, final summary with elapsed time per step, LLM token usage per step, link to event log.

### 5. Hero scenario 1 — `scenarios/customer_signup_and_exhaust.yaml` (deterministic)

Demonstrates the full happy-path flow with deterministic steps:
- Customer create + KYC attestation + COF + order flow (COM → SOM → provisioning-sim → subscription activation)
- Usage → bundle decrement → exhaustion → block
- Mediation ingress rejection (block-on-exhaust doctrine at the edge)
- VAS top-up → unblock
- Usage resumes

All steps use `action:` (direct tool calls). This is the regression test for the service layer, event chain, and policy enforcement. Runs in ~3-5 seconds per invocation.

Tagged `[hero, smoke, regression, deterministic]`.

### 6. Hero scenario 2 — `scenarios/new_activation_with_provisioning_retry.yaml` (deterministic)

Demonstrates provisioning resilience with deterministic steps:
- Enables HLR fail-first-attempt fault injection
- Places an order via direct `order.create`
- Verifies SOM retries the failed task
- Verifies the order still completes
- Verifies the event sequence includes the retry

All steps use `action:`. Runs in ~8-12 seconds (because of the fault injection delay).

Tagged `[hero, resilience, provisioning, deterministic]`.

### 7. Hero scenario 3 — `scenarios/llm_troubleshoot_blocked_subscription.yaml` (LLM-driven) — SHIP GATE

**This is the scenario that proves the LLM is load-bearing, not decorative.**

```yaml
name: llm_troubleshoot_blocked_subscription
description: |
  An LLM-driven troubleshooting scenario. Setup is deterministic (create customer,
  COF, order, burn data to exhaustion). The core step passes a natural-language
  problem description to the real LLM and asserts that the LLM correctly diagnoses
  the blocked state, reads the balance, checks available VAS offerings, purchases
  the right one, and verifies the subscription is active again.

  This scenario is a v0.1 ship gate. If it doesn't pass with the default model
  (MiMo v2 Flash), the LLM path is broken and v0.1 is not shippable as "LLM-native".

tags: [hero, llm, ship_gate, reasoning]

setup:
  reset_operational_data: true
  freeze_clock_at: "2026-04-11T14:00:00+08:00"

variables:
  customer_email: "llm-demo-{{ run_id }}@bss-cli.local"
  plan: PLAN_S

# === DETERMINISTIC SETUP ===
# We drive the setup via direct tool calls to keep it fast and reproducible.
# Once everything is in place, we hand over to the LLM for the real test.

steps:
  - name: create customer
    action: customer.create
    args:
      name: "LLM Demo"
      email: "{{ customer_email }}"
      phone: "+6590008888"
    capture:
      customer_id: "$.id"

  - name: attest KYC
    action: customer.attest_kyc
    args:
      customer_id: "{{ customer_id }}"
      provider: myinfo
      provider_reference: "llm-demo-{{ run_id }}"
      document_type: nric
      document_number: "S{{ run_id }}B"
      document_country: SG
      date_of_birth: "1985-03-15"
      nationality: SG
      attestation_payload:
        issuer: singpass.gov.sg
        signature: "stub-signature"

  - name: add card on file
    action: payment.add_card
    args:
      customer_id: "{{ customer_id }}"
      card_number: "4242424242424242"
      exp_month: 12
      exp_year: 2030
      cvv: "123"

  - name: place order (direct, not via LLM)
    action: order.create
    args:
      customer_id: "{{ customer_id }}"
      offering_id: "{{ plan }}"
    capture:
      order_id: "$.id"

  - name: wait for activation
    action: order.wait_until
    args:
      order_id: "{{ order_id }}"
      state: completed
      timeout_seconds: 10

  - name: get the subscription
    action: subscription.list_for_customer
    args:
      customer_id: "{{ customer_id }}"
    capture:
      subscription_id: "$[0].id"
      msisdn: "$[0].msisdn"

  - name: verify subscription active before exhaustion
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: active
        balances.data.remaining: 5120   # 5 GB on PLAN_S

  # Burn the bundle deliberately to set up the problem the LLM will solve
  - name: burn 4 GB
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 4096, unit: mb }

  - name: burn final 1 GB (exhausts bundle)
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 1024, unit: mb }

  - name: verify blocked before handing to LLM
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: blocked
      poll:
        interval_ms: 100
        timeout_seconds: 5

  # === LLM HAND-OVER ===
  # The environment is now set up. Customer exists, COF exists, subscription is
  # blocked due to exhaustion. Hand over to the LLM with a natural-language
  # problem description and see if it figures out the right fix.

  - name: LLM diagnoses and fixes the blocked subscription
    ask: |
      The customer with email {{ customer_email }} (customer id {{ customer_id }})
      called support. They say their data stopped working. Figure out what's wrong
      with their subscription and fix it if possible. If you can't fix it without
      doing something destructive, explain what you'd need to do and stop — don't
      take destructive actions without explicit approval.
    timeout_seconds: 90

    # Required: the LLM MUST call these tools at least once.
    expect_tools_called_include:
      - subscription.list_for_customer
      - subscription.get
      - subscription.get_balance
      - catalog.list_vas
      - subscription.purchase_vas

    # Forbidden: the LLM MUST NOT call these tools.
    expect_tools_not_called:
      - subscription.terminate
      - customer.close
      - admin.force_state
      - admin.reset_operational_data

    # Final state: after the LLM is done, the subscription must be active.
    expect_final_state:
      resource: subscription
      id: "{{ subscription_id }}"
      state: active
      balances.data.remaining: { gt: 0 }

    # Event trace: a successful fix must emit these events in causal order.
    expect_event_sequence:
      - subscription.vas_purchased
      - subscription.unblocked

    allow_clarification: false

  # === DETERMINISTIC VERIFICATION ===
  # Belt-and-braces: re-read the subscription state via direct tool call after
  # the LLM finishes. The LLM's self-reported success is not sufficient.

  - name: verify subscription is active again (post-LLM verification)
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: active
        balances.data.remaining: { gt: 0 }

  - name: verify usage flows again
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 100, unit: mb }

  - name: verify the LLM's actions are logged in the customer's interaction history
    assert:
      tool: customer.get_interactions
      args: { customer_id: "{{ customer_id }}", limit: 20 }
      expect:
        # At least one interaction should have channel=llm
        any_match:
          channel: llm
          actor: { starts_with: "llm-" }

teardown:
  unfreeze_clock: true
```

**What this scenario proves:**

1. **The LLM can diagnose from natural language.** "Data stopped working" with no technical vocabulary. The LLM must translate this to the right diagnostic steps.

2. **The LLM uses the semantic layer correctly.** It reads docstrings, picks the right tools, uses typed IDs, handles the tool results, decides what to do next.

3. **The LLM respects destructive operation gating.** `subscription.terminate` is in the forbidden list. If the LLM reaches for it without `--allow-destructive`, the scenario fails.

4. **The LLM interprets structured errors.** It sees `state: blocked` and knows this means "bundle exhausted, needs top-up" because the system prompt and the error recovery patterns tell it so.

5. **The end state is verified by direct tool call.** We don't trust the LLM's self-report — we re-read the system state after the LLM finishes and confirm it's actually correct. LLMs can be confidently wrong; verification can't.

6. **The audit trail attributes actions correctly.** The final assertion walks the customer's interaction log and confirms the LLM-channel actions are present. This proves channel injection works in LLM mode, not just direct mode.

7. **It's ship-gate critical.** If MiMo v2 Flash can't handle this, either the semantic layer needs tightening, the system prompt needs iteration, or we swap to a stronger model. In any case, v0.1 doesn't ship until this scenario is green against a real model.

### 8. Mandatory code grep before building the runner — precondition

```bash
grep -rn "datetime.utcnow\|datetime.now()" --include="*.py" services/ packages/
```

Must return zero hits outside the `clock` service itself. Fix any violations in a separate `chore: route datetime through clock service` commit BEFORE touching the scenario runner.

## Verification checklist

### Pre-work (admin reset)

- [ ] `POST /admin-api/v1/reset-operational-data` exists and works end-to-end
- [ ] Reset spares reference data (catalog, agents, MSISDN/eSIM pool identities)
- [ ] Reset spares Campaign OS schemas (verified by count-before, count-after)
- [ ] `BSS_ALLOW_ADMIN_RESET=false` → endpoint returns 403
- [ ] `bss admin reset` (interactive) prompts for confirmation
- [ ] `bss admin reset --yes` runs without prompting
- [ ] `bss admin reset --reset-sequences` resets ID sequences
- [ ] Reset action appears in `audit.domain_event` with `cli` channel
- [ ] Pre-work landed as separate chore commit on main before phase-10 branch cut

### Scenario runner + datetime

- [ ] Datetime grep returns zero hits outside the clock service (precondition)
- [ ] `bss scenario validate scenarios/*.yaml` — all three files parse clean
- [ ] `bss scenario run scenarios/customer_signup_and_exhaust.yaml` passes from a clean DB (deterministic, ~3-5s)
- [ ] Same scenario passes again immediately (idempotent reset)
- [ ] `bss scenario run scenarios/new_activation_with_provisioning_retry.yaml` passes (deterministic, ~8-12s)
- [ ] `bss scenario run scenarios/llm_troubleshoot_blocked_subscription.yaml` passes against the real OpenRouter model (LLM-driven, ~30-90s, costs under a cent)
- [ ] The LLM scenario passes **three runs in a row** (non-determinism check)
- [ ] `--no-llm` flag: LLM scenario fails with clear error that `ask:` steps are disabled
- [ ] Running all three scenarios back-to-back → all pass, no cross-contamination
- [ ] Deliberately break a step → runner reports which step failed, actual-vs-expected diff, step duration, LLM token usage for LLM steps
- [ ] LLM step reporting shows: tools called (and whether expected set was satisfied), tools forbidden (and whether any were triggered), total LLM tokens and cost
- [ ] `make scenarios-deterministic` runs scenarios 1 and 2 as part of CI
- [ ] `make scenarios-llm` runs scenario 3, marked as requiring OpenRouter
- [ ] `make scenarios-all` runs all three, used before v0.1.0 tag

## v0.1 Ship Criteria — this is the release gate

- [ ] All 10 phases complete, every phase's verification checklist passed
- [ ] `docker compose up` → `make seed` → `bss scenario run scenarios/customer_signup_and_exhaust.yaml` → green on a fresh clone (deterministic path works)
- [ ] `bss scenario run scenarios/new_activation_with_provisioning_retry.yaml` → green (resilience path works)
- [ ] **`bss scenario run scenarios/llm_troubleshoot_blocked_subscription.yaml` → green, three runs in a row, against the default model (`xiaomi/mimo-v2-flash`)** — the LLM path works
- [ ] `bss admin reset --yes` followed by `bss scenario run ...` works from a dirty state (proves the manual reset path)
- [ ] Stack RSS under 4 GB (`docker stats` snapshot committed as evidence)
- [ ] Cold start under 30 seconds (measured)
- [ ] Internal p99 API latency under 50ms (measured during exhaustion scenario)
- [ ] `README.md` quickstart tested on a fresh machine
- [ ] `LICENSE` is Apache-2.0
- [ ] `CLAUDE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `TOOL_SURFACE.md`, `DECISIONS.md` all reflect the shipped state
- [ ] Campaign OS schemas untouched across the entire v0.1 build history
- [ ] Tag `v0.1.0`

**Non-negotiable:** the LLM scenario is a ship gate. If it's flaky or failing, diagnose the cause (semantic layer, system prompt, model capability) and fix before tagging v0.1.0. Do not ship v0.1 without a green LLM scenario. "LLM-native BSS" that doesn't actually prove the LLM works is marketing, not product.

## Out of scope for v0.1

- Scenario parallelization
- Scenario composition (one scenario calling another)
- Random/fuzz scenarios
- Data volume / load scenarios
- Scenario recording from REPL (auto-capture)
- More than one LLM-mode hero scenario (one is sufficient for the ship gate; more come in v0.2)
- `bss admin reset-reference-data` (would wipe catalog/agents/pools — nuclear, deferred to v0.2 if needed)
- `bss admin reset --schema <name>` (surgical reset per schema — v0.2)

## Post-v0.1 backlog (Phase 11+)

- **Multiple LLM scenarios** covering different reasoning patterns: ambiguity resolution, multi-customer disambiguation, escalation decisions, refund handling
- **LLM scenario matrix** across multiple models (MiMo, Sonnet, GPT-4o) to compare tool-calling quality
- **OpenTelemetry wire-through**, `bss trace` ASCII swimlane
- Metabase dashboards
- Renewal scheduler, VAS expiry
- TMF REST hardening
- Multi-tenancy activation
- Authentication (Phase 12)
- Organization party type
- Multi-CFS products
- Scenario record/replay from REPL
- CDR file ingestion
- `bss doctor` health check
- Nuclear/surgical reset variants

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `TOOL_SURFACE.md`, `DECISIONS.md`, `phases/PHASE_09.md`, and `phases/PHASE_10.md`.
>
> **Phase 10 has three hero scenarios, not two. The third is LLM-driven and is a v0.1 ship gate.** Do not skip it.
>
> **Phase 10 also has pre-work (section 0) that must land as a separate chore commit on main BEFORE the phase-10 branch is cut:**
>
> 1. `admin.reset_operational_data` endpoint
> 2. `bss admin reset` CLI command
>
> Do the pre-work first, verify it, commit it to main with a `chore:` prefix, then cut the phase-10 branch for the scenario runner work.
>
> **Precondition checks before planning:**
>
> ```bash
> # Datetime discipline
> grep -rn "datetime.utcnow\|datetime.now()" --include="*.py" services/ packages/
>
> # Phase 9 is tagged and LLM path works
> git tag | grep phase-09
> bss ask "show me catalog plans"
> ```
>
> If any datetime hits exist outside the `clock` service, stop. These must be fixed in a separate `chore: route datetime through clock service` commit on main BEFORE Phase 10 starts. If `bss ask` doesn't work, stop and fix before Phase 10.
>
> Once preconditions are clean, produce the full plan:
>
> 1. **Pre-work design** — paste the endpoint spec (URL, request/response schema, policy guards), the CLI command UX, the env var gate, the schema allowlist, and the verification queries that prove Campaign OS is untouched.
>
> 2. **YAML schema as pydantic models** — paste the full `Scenario`, `Step`, `Action`, `Ask`, `Assertion`, `Setup`, `Teardown`, `ExpectError`, `ExpectToolsCalled`, `ExpectFinalState`, `ExpectEventSequence` models. Confirm both `action:` and `ask:` step types are supported.
>
> 3. **Action registry** — list every action name the runner supports for deterministic mode and confirm each maps 1:1 to an existing orchestrator tool from Phase 9.
>
> 4. **LLM executor design** — paste the `llm_executor.py` design showing how an `ask:` step constructs the LangGraph orchestrator, injects variable context, runs the graph, captures tool trace, verifies expectations, reports results. Confirm it uses the same `AsyncOpenAI` → OpenRouter client constructed in Phase 9.
>
> 5. **Hero scenario walkthroughs** — for each of the three hero scenarios, walk through step-by-step and predict what events should appear in `audit.domain_event`. For scenario 3, predict what tool sequence the LLM is likely to take based on the system prompt and semantic layer.
>
> 6. **Expectation semantics** — paste the matching logic for `expect_tools_called_include` (subset match), `expect_tools_not_called` (disjoint match), `expect_final_state` (dot-path match with operators like `gt`, `not_null`, `starts_with`), `expect_event_sequence` (causal subsequence match).
>
> 7. **Reset + freeze mechanics** — confirm `admin.reset_operational_data` (pre-work from step 1) is the single reset code path used by both `bss admin reset` and `setup.reset_operational_data: true` in scenarios. Confirm `clock.freeze` propagates.
>
> 8. **Reporting format** — paste sample pass output and sample fail output. For LLM steps, reporting must show: tools called (✓/✗ against expected), forbidden tools triggered (✗ if any), final state check (✓/✗ per field), event sequence match (✓/✗), total tokens used, total cost in USD.
>
> 9. **v0.1 ship criteria self-check** — run each line of the ship criteria checklist and confirm it's achievable. Flag anything borderline. Specifically call out the "LLM scenario passes three runs in a row" criterion and propose what to do if it's flaky.
>
> Wait for my approval before writing any code.
>
> After I approve, implement in this order:
>
> **Pre-work (separate chore commit on main):**
> 1. `admin.reset_operational_data` endpoint with policy guard and schema allowlist
> 2. `bss admin reset` CLI command with interactive confirmation and `--yes` flag
> 3. Pre-work verification checklist
> 4. Chore commit to main: `chore: admin.reset_operational_data endpoint + bss admin reset CLI`
> 5. Push to origin/main
>
> **Phase 10 proper (phase-10 branch):**
> 6. YAML schema + validator (`bss scenario validate` works)
> 7. Deterministic runner: action registry + variable interpolation + capture
> 8. Assertion evaluator with polling
> 9. Setup/teardown (uses the pre-work reset endpoint)
> 10. Hero scenario 1 (deterministic) → iterate until green
> 11. Hero scenario 2 (deterministic with fault injection) → iterate until green
> 12. LLM executor (`llm_executor.py`) — wraps the Phase 9 orchestrator, captures tool trace
> 13. LLM expectation evaluators
> 14. Hero scenario 3 (LLM-driven) → iterate until green, three runs in a row
> 15. Reporter polish — especially LLM step reporting (tokens, cost, tool trace)
> 16. Full v0.1 ship criteria checklist
>
> **Do not tag v0.1.0 yourself — that's my job after I verify on a fresh clone.**

## The trap

**The LLM scenario is the whole point of v0.1.** If you skip it or water it down, v0.1 is a BSS with an LLM demo, not an LLM-native BSS. Do not let Claude Code propose "we'll add the LLM scenario in Phase 11" — it's Phase 10 or bust.

**Don't trust the LLM's self-report.** Always verify the final state with a direct tool call after the LLM finishes. LLMs can be confidently wrong. Verification can't.

**If the LLM scenario is flaky, the fix is the semantic layer, not the test.** Don't add retry loops or relax the assertions. If MiMo v2 Flash can't diagnose a blocked subscription three times in a row, either the system prompt needs iteration, the docstrings need tightening, or the error recovery patterns need more examples. The test should stay strict.

**The pre-work is not "nice to have" — it's a dependency.** The scenario runner's `setup.reset_operational_data: true` needs an endpoint to call. Building the runner first and the endpoint later creates a chicken-and-egg problem where scenarios can't be tested until the endpoint exists. Do the pre-work first, verify it with direct curl/bsspsql, commit it as a chore, THEN start the scenario runner branch.

**Don't let the admin reset become surgical.** `bss admin reset` is intentionally blunt: wipe operational data, preserve reference data, done. Resist the temptation to add `--only-customers`, `--only-orders`, `--keep-one <id>`, etc. Those are v0.2 concerns at most. v0.1 has one reset UX and it's the simple one.

**Don't let Claude Code quietly widen scope.** Scenario runners attract feature creep — parallel steps, conditional branches, loops, HTTP mocking. Stop it. v0.1 needs deterministic steps, LLM steps, variable interpolation, capture, assertions, polling. Nothing more.

**Ship when green.** When all three scenarios pass on a fresh clone, you are done. The LLM scenario must pass three times in a row, but after that, stop. v0.1 is a foundation, not a destination.

**Don't let the datetime grep become "just skip those, they're tests".** If any non-test code uses wall clock, scenarios will silently fail on certain days or at certain times. Fix all of them first.

**MiMo costs are not a constraint.** Phase 9 dev hit $0.008 total including 18+ LLM calls. The LLM scenario running three times in a row costs maybe 3 cents. Don't let anyone propose "skip the real-LLM runs to save money" — the money is rounding error and the three-runs check is what catches non-determinism.
