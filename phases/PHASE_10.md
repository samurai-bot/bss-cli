# Phase 10 — Scenario Runner + Hero Scenarios

> **The shipping phase.** When this is green, v0.1 is done.

## Goal

A YAML scenario runner and the two hero scenarios that prove the system works end-to-end. These scenarios are also the seed mechanism for demo data, the regression test suite, and the thing you'll show on LinkedIn.

## Deliverables

### 1. Scenario runner (`cli/bss_cli/scenarios/`)

```
cli/bss_cli/scenarios/
├── __init__.py
├── runner.py           # main loop
├── schema.py           # pydantic models for YAML
├── actions.py          # action registry (maps action name → tool call)
├── assertions.py       # assertion evaluator with polling
├── context.py          # variable interpolation + captured values
└── reporting.py        # pass/fail rendering
```

Invoked via:
```
bss scenario run scenarios/customer_signup_and_exhaust.yaml
bss scenario run scenarios/new_activation_with_provisioning_retry.yaml
bss scenario list
bss scenario validate scenarios/*.yaml
```

### 2. Scenario YAML schema

```yaml
name: customer_signup_and_exhaust
description: |
  Creates a customer, attaches COF, orders PLAN_S, simulates usage to exhaustion,
  verifies blocking, tops up via VAS, verifies unblocking.
tags: [hero, smoke, regression]

setup:
  reset_operational_data: true      # calls admin.reset_operational_data before starting
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

  - name: attest KYC (simulating channel-layer Myinfo flow)
    action: customer.attest_kyc
    args:
      customer_id: "{{ customer_id }}"
      provider: myinfo
      provider_reference: "myinfo-scenario-{{ run_id }}"
      document_type: nric
      document_number: "S{{ run_id }}A"
      document_country: SG
      date_of_birth: "1985-03-15"
      nationality: SG
      attestation_payload:
        issuer: singpass.gov.sg
        signature: "stub-signature-for-v0.1"

  - name: verify KYC status
    assert:
      tool: customer.get_kyc_status
      args: { customer_id: "{{ customer_id }}" }
      expect:
        kyc_status: verified
        kyc_verification_method: myinfo

  - name: add card on file
    action: payment.add_card
    args:
      customer_id: "{{ customer_id }}"
      card_number: "4242424242424242"
      exp_month: 12
      exp_year: 2030
      cvv: "123"
    capture:
      payment_method_id: "$.id"

  - name: place order
    action: order.create
    args:
      customer_id: "{{ customer_id }}"
      offering_id: "{{ plan }}"
    capture:
      order_id: "$.id"

  - name: wait for order completion
    action: order.wait_until
    args:
      order_id: "{{ order_id }}"
      state: completed
      timeout_seconds: 10

  - name: get subscription
    action: subscription.list_for_customer
    args:
      customer_id: "{{ customer_id }}"
    capture:
      subscription_id: "$[0].id"
      msisdn: "$[0].msisdn"
      iccid: "$[0].iccid"

  - name: verify subscription is active with eSIM binding
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: active
        balances.data.remaining: 5120   # 5 GB in MB
        msisdn: { not_null: true }
        iccid: { not_null: true }

  - name: verify eSIM activation code is retrievable
    assert:
      tool: subscription.get_esim_activation
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        iccid: "{{ iccid }}"
        activation_code: { starts_with: "LPA:1$smdp.bss-cli.local$" }

  - name: burn data — 4 GB
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 4096, unit: mb }

  - name: burn data — 1 GB (exhausts bundle)
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 1024, unit: mb }

  - name: verify blocked
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: blocked
      poll:
        interval_ms: 100
        timeout_seconds: 5

  - name: verify next usage is rejected at ingress
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 100, unit: mb }
    expect_error:
      code: POLICY_VIOLATION
      rule: usage.record.subscription_must_be_active

  - name: top up with VAS 5GB
    action: subscription.purchase_vas
    args:
      subscription_id: "{{ subscription_id }}"
      vas_offering_id: VAS_DATA_5GB

  - name: verify unblocked
    assert:
      tool: subscription.get
      args: { subscription_id: "{{ subscription_id }}" }
      expect:
        state: active
        balances.data.remaining: 5120

  - name: verify usage flows again
    action: usage.simulate
    args: { msisdn: "{{ msisdn }}", type: data, quantity: 500, unit: mb }

teardown:
  unfreeze_clock: true
```

### 3. Runner mechanics

- **Variable interpolation:** `{{ var }}` Jinja-style, substituted at step evaluation time (not load time). Captures from earlier steps are available.
- **Capture:** JSONPath expressions using `jsonpath-ng` to pull values out of tool results into the variable context.
- **Assertions:** dot-path field checks against tool result. Supports polling (`poll.interval_ms`, `poll.timeout_seconds`) for async-settling state. Fails cleanly with actual-vs-expected diff.
- **expect_error:** step succeeds if the action raises a `PolicyViolationFromServer` matching the given `code` and `rule`.
- **reset_operational_data:** calls `admin.reset_operational_data` — wipes operational tables (subscriptions, orders, services, payments, usage, cases, tickets, interactions) while preserving reference data (catalog, agents, SLA policies, MSISDN pool, fault rules). Reference data stays. This is the "clean slate per scenario" mechanism.
- **freeze_clock_at:** calls `clock.freeze` with the given timestamp. All services read time via the clock service, so the whole stack operates at the frozen time. `teardown.unfreeze_clock` restores wall clock at the end.
- **Channel injection:** runner sets `X-BSS-Channel: scenario` and `X-BSS-Actor: scenario:<name>` on every call. Every step auto-logs to `interaction` via the CRM auto-logging in Phase 4.
- **Reporting:** structured pass/fail per step, final summary with elapsed time per step, full event log link (`bss trace events --since <start>`).

### 4. Hero scenario 1: `scenarios/customer_signup_and_exhaust.yaml`

Per the YAML above. Demonstrates:
- Customer create + COF + order flow (COM → SOM → provisioning-sim → subscription activation)
- Usage → bundle decrement → exhaustion → block
- Mediation ingress rejection (block-on-exhaust doctrine at the edge)
- VAS top-up → unblock
- Usage resumes

### 5. Hero scenario 2: `scenarios/new_activation_with_provisioning_retry.yaml`

```yaml
name: new_activation_with_provisioning_retry
description: |
  Enables HLR fail-first-attempt fault injection, places an order, verifies that
  SOM retries and the activation still completes. Proves the retry flow, the
  provisioning simulator's fault injection, and end-to-end resilience.
tags: [hero, resilience, provisioning]

setup:
  reset_operational_data: true
  freeze_clock_at: "2026-04-11T10:00:00+08:00"

variables:
  customer_email: "retry-demo-{{ run_id }}@bss-cli.local"
  plan: PLAN_M

steps:
  - name: enable HLR fail-first-attempt
    action: provisioning.set_fault_injection
    args:
      task_type: HLR_PROVISION
      fault_type: fail_first_attempt
      probability: 1.0      # deterministic for the scenario
      enabled: true

  - name: create customer
    action: customer.create
    args:
      name: "Retry Demo"
      email: "{{ customer_email }}"
      phone: "+6590009999"
    capture:
      customer_id: "$.id"

  - name: add card on file
    action: payment.add_card
    args:
      customer_id: "{{ customer_id }}"
      card_number: "4242424242424242"
      exp_month: 12
      exp_year: 2030
      cvv: "123"

  - name: place order
    action: order.create
    args:
      customer_id: "{{ customer_id }}"
      offering_id: "{{ plan }}"
    capture:
      order_id: "$.id"

  - name: wait for order completion (must survive the retry)
    action: order.wait_until
    args:
      order_id: "{{ order_id }}"
      state: completed
      timeout_seconds: 15

  - name: verify order completed despite first-attempt failure
    assert:
      tool: order.get
      args: { order_id: "{{ order_id }}" }
      expect:
        state: completed

  - name: verify at least one HLR task had 2 attempts
    assert:
      tool: provisioning.list_tasks
      args:
        filter:
          related_order_id: "{{ order_id }}"
          task_type: HLR_PROVISION
      expect_any:
        attempts: 2
        state: completed

  - name: verify subscription active
    action: subscription.list_for_customer
    args: { customer_id: "{{ customer_id }}" }
    capture:
      subscription_id: "$[0].id"
    assert_captured:
      subscription_id: { not_null: true }

  - name: verify trace shows the retry sequence
    action: trace.for_order
    args: { order_id: "{{ order_id }}" }
    expect_event_sequence:
      - order.acknowledged
      - order.in_progress
      - service_order.created
      - provisioning.task.created
      - provisioning.task.started
      - provisioning.task.failed        # first attempt
      - provisioning.task.started       # retry
      - provisioning.task.completed
      - service.activated
      - service_order.completed
      - order.completed
      - subscription.activated

teardown:
  unfreeze_clock: true
  cleanup_fault_injection:
    - { task_type: HLR_PROVISION, fault_type: fail_first_attempt, enabled: false }
```

Demonstrates:
- Configurable fault injection (the simulator doing its job)
- SOM retry semantics (policy `provisioning_task.retry.max_attempts`)
- Event-driven resilience (the chain survives a failure)
- `bss trace` shows the full story including the retry

### 6. Mandatory code grep before building the runner

```bash
grep -rn "datetime.utcnow\|datetime.now()" --include="*.py" services/ packages/
```

Must return **zero hits** outside the `clock` service itself. If anything uses wall clock directly, `freeze_clock_at` will silently not work. Fix any violations BEFORE building the runner — otherwise scenarios are non-deterministic and you'll chase ghost failures.

## Verification checklist

- [ ] `bss scenario validate scenarios/*.yaml` — both files parse clean
- [ ] `bss scenario run scenarios/customer_signup_and_exhaust.yaml` passes from a clean DB
- [ ] Same scenario passes again immediately (idempotent reset)
- [ ] `bss scenario run scenarios/new_activation_with_provisioning_retry.yaml` passes
- [ ] Retry scenario genuinely observes 2 attempts on the HLR task (not just a lucky first success)
- [ ] Fault injection is cleaned up after scenario (state returns to default)
- [ ] Clock frozen during scenario, unfrozen after
- [ ] Running both scenarios back-to-back → both pass, no cross-contamination
- [ ] Deliberately break a step → runner reports which step failed, actual-vs-expected diff, step duration
- [ ] `make scenarios` runs both hero scenarios in sequence as part of CI

## v0.1 Ship Criteria (this is the release gate)

- [ ] All 10 phases complete, every phase's verification checklist passed
- [ ] `docker compose up` → `make seed` → `bss scenario run scenarios/customer_signup_and_exhaust.yaml` → green on a fresh clone
- [ ] `bss scenario run scenarios/new_activation_with_provisioning_retry.yaml` → green
- [ ] Stack RSS under 4 GB (`docker stats` snapshot committed as evidence)
- [ ] Cold start under 30 seconds (measured)
- [ ] Internal p99 API latency under 50ms (measured during exhaustion scenario)
- [ ] `README.md` quickstart tested on a fresh machine
- [ ] `LICENSE` is Apache-2.0
- [ ] `CLAUDE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `TOOL_SURFACE.md`, `DECISIONS.md` all reflect the shipped state
- [ ] Tag `v0.1.0`

## Out of scope (v0.1)

- Scenario parallelization
- Scenario composition (one scenario calling another)
- Random/fuzz scenarios
- Data volume / load scenarios
- Scenario recording from REPL (auto-capture)

## Post-v0.1 backlog (Phase 11+)

- **OpenTelemetry wire-through:** real traces across all services, Jaeger/Tempo container
- **`bss trace` ASCII swimlane:** renders OTel spans as per-service lanes with time axis — the visualization that turns BSS-CLI into a teaching tool
- **Metabase dashboards:** pre-built dashboards reading `audit.domain_event` for customer ops, provisioning SLOs, usage trends
- **Renewal scheduler:** background job that renews active subscriptions on period boundary, charges COF, handles failures → blocked
- **VAS expiry:** 24h unlimited day pass enforcement via scheduled job
- **TMF REST hardening:** full conformance against TMF reference payloads, pagination, filtering, fields selection
- **Multi-tenancy activation:** real tenant scoping via header + policy
- **Authentication:** OAuth2 client credentials per service
- **Organization party type:** business customers
- **Multi-CFS products:** plans with add-ons as separate CFS
- **Scenario record/replay:** capture a REPL session as a scenario YAML
- **CDR file ingestion:** batch usage file drop
- **`bss doctor`:** health check + diagnostic command

## Session prompt

> Read `CLAUDE.md`, `phases/PHASE_09.md`, `phases/PHASE_10.md`.
>
> Before writing any code:
> 1. Run the datetime grep and paste the results. If any hits exist, fix them first in a separate commit.
> 2. Paste the full YAML schema as a pydantic model
> 3. List every action name the runner will support and confirm each maps to an existing orchestrator tool
> 4. Walk through both hero scenarios step-by-step and predict what events should appear in `audit.domain_event`
>
> Wait for approval. Implement in this order:
> 1. Schema + validator (`bss scenario validate` works)
> 2. Action registry + variable interpolation + capture (simplest steps work)
> 3. Assertion evaluator with polling
> 4. Setup/teardown (reset + clock freeze)
> 5. Hero scenario 1 → iterate until green
> 6. Hero scenario 2 → iterate until green
> 7. Reporter polish
>
> After green, run the v0.1 ship criteria checklist. Do not tag v0.1.0 yourself — that's my job.

## The discipline

**The retry scenario is the whole point of the v2 rework.** If it doesn't prove the SOM retry flow visibly, the SOM and simulator work was wasted. Do not cut the `expect_event_sequence` assertion — it's what turns "it worked" into "I can see it worked, and so can a LinkedIn reader".

**Don't let Claude Code quietly widen scope.** Scenario runners attract feature creep — parallel steps, conditional branches, loops, HTTP mocking. Stop it. v0.1 only needs linear steps with variable interpolation, capture, assertions, and polling. Anything more is Phase 11+.

**Ship when green.** When both scenarios pass on a fresh clone, you are done. Resist the urge to add "just one more thing" before tagging. v0.1 is a foundation, not a destination.
