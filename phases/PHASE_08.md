# Phase 8 — Mediation + Rating (the usage flow)

## Goal

Close the loop from usage events back to bundle balance decrement and exhaustion. Mediation ingests, Rating consumes, Subscription decrements. By the end of this phase, `usage.simulate` causes real balance depletion and real blocking at the network edge.

Shorter phase — mostly event wiring over domain logic that already exists from Phase 6.

### What this phase is — and isn't

**This is TMF635 online mediation, not batch mediation, and not an OCS.**

- **Online mediation (what we build):** single usage event in, synchronous block-at-edge policy, per-event balance decrement via events, reject-on-exhaust in the request path. Mediation behaves as the customer-facing accounting surface of the usage plane.
- **Batch mediation (what we don't build):** CDR file ingest, hourly/daily aggregation, deduplication/correlation, rerating windows. Motto #1 (bundled-prepaid only) removes the reason it would exist — there are no per-unit charges to roll up into an invoice.
- **OCS (abstracted outside BSS-CLI):** Diameter Gy/Ro signalling, PCEF quota grants, quota reservation, `Final-Unit-Indication` to the packet core. A real deployment would have an external OCS on the network side making the live authorize/deny decisions against the PCEF/GGSN. BSS-CLI's "block at the network edge" is a REST-layer approximation of the customer-visible effect of an OCS quota depletion — it does not sit on the data plane.

If this distinction blurs (e.g., someone proposes adding a batch rerating job here, or pretends the `POST /usage` endpoint is a Diameter substitute), stop and re-read this section. The doctrine depends on this boundary being sharp.

## Deliverables

### Service: `services/mediation/` (port **8007**)

Clone the Phase 5/6 service pattern.

**Endpoints (TMF635):**
- `POST /tmf-api/usageManagement/v4/usage` — ingest a single usage event (used by `usage.simulate`, the scenario runner, and eventually the CLI)
- `GET  /tmf-api/usageManagement/v4/usage?subscriptionId={id}&since={ts}&type={type}`
- `GET  /tmf-api/usageManagement/v4/usage/{id}`
- `GET /health`, `GET /ready`

**Flow:**
1. Receive usage event
2. Enrich: look up subscription by MSISDN via `bss-clients.SubscriptionClient.get_by_msisdn(msisdn)`. If no subscription → store with `processing_error='no_active_subscription'` and return 422.
3. **Blocked-subscription rule:** if subscription is in `blocked` state → store with `processing_error='subscription_blocked'` and return 422. **No usage is recorded for blocked subs.** This is the "block-on-exhaust" doctrine enforced at the network edge.
4. Persist to `mediation.usage_event` with `processed=false`
5. Emit `usage.recorded` with full enriched payload
6. Return 201

### Service: `services/rating/` (port **8008**)

Minimal service, mostly event-driven.

**Endpoints:**
- `GET /rating-api/v1/tariff/{offering_id}` — debug/inspection
- `POST /rating-api/v1/rate-test` — test endpoint: take a usage event payload, return what the rating would be, don't persist
- `GET /health`, `GET /ready`

**Core — tariff lookup + pure rating function** (`app/domain/rating.py`):

```python
def rate_usage(
    usage: UsageEvent,
    tariff: Tariff,
    balance: BundleBalance,
) -> RatingResult:
    """
    Pure function. Returns (consumed_quantity, charge_amount, allowance_type).
    For bundled prepaid v0.1: charge_amount is always 0 (bundle is prepaid).
    consumed_quantity == usage quantity (no tiering, no time-of-day rules).
    """
```

**Why rating is trivial in v0.1:** bundled prepaid means no per-unit charging. Usage just decrements the bundle. Rating becomes a unit-conversion + allowance-mapping function. Doctrine simplification paying off.

The rating service is still a separate service because (a) architecturally correct per SID, (b) future rating rules can live here without touching Subscription.

**Events consumed:**
- `usage.recorded` → look up tariff for the subscription's offering → call `rate_usage` → emit `usage.rated`

**Events published:**
- `usage.rated` — payload includes the decrement instruction for Subscription

### Subscription service updates

Replace the Phase 6 test-only `consume-for-test` endpoint with a real consumer for `usage.rated`:

```python
async def handle_usage_rated(event: UsageRatedEvent):
    subscription = await repo.get(event.subscription_id)
    if subscription.state != "active":
        # Guard: shouldn't happen because Mediation rejects at ingress,
        # but belt-and-braces for replayed events or race conditions.
        logger.warning("usage.rated for non-active subscription", 
                       subscription_id=event.subscription_id, state=subscription.state)
        return

    # Serialize per-subscription decrement — see concurrency section below
    async with repo.session.begin():
        # SELECT ... FOR UPDATE on the balance row
        current = await repo.get_balance_for_update(
            subscription.id, event.allowance_type
        )
        new_balance = bundle.consume(
            balance=current,
            quantity=event.consumed_quantity,
            allowance_type=event.allowance_type,
        )
        await repo.update_balance(new_balance)

        if bundle.is_exhausted([new_balance], primary_type="data"):
            await transition(subscription, "exhaust")
            # Automatically publishes subscription.exhausted and subscription.blocked
```

**Remove or gate the Phase 6 test endpoint.** `POST /subscription/{id}/consume-for-test` must either be deleted in this phase, or hidden behind `BSS_ENABLE_TEST_ENDPOINTS=true` with a default of `false`. Preferred: delete it. The real consumer (`handle_usage_rated`) replaces it.

### Concurrency — the decrement trap

Two concurrent `usage.rated` events for the same subscription can race:
- Both read `balance=100`
- Both compute `new_balance=50`
- Last write wins
- You lost 50 units of consumption

This is the trap every usage pipeline hits. For v0.1, use **Option A: `SELECT ... FOR UPDATE` per subscription**. Simplest, correct, good enough at BSS-CLI's scale.

```python
# In SubscriptionRepository
async def get_balance_for_update(self, subscription_id: str, allowance_type: str) -> BundleBalance:
    stmt = (
        select(BundleBalance)
        .where(BundleBalance.subscription_id == subscription_id)
        .where(BundleBalance.allowance_type == allowance_type)
        .with_for_update()
    )
    return (await self.session.execute(stmt)).scalar_one()
```

Alternatives considered:
- **Option B (optimistic locking):** version column, retry on conflict. More complex, higher throughput ceiling. Over-engineered for v0.1.
- **Option C (RabbitMQ partition by subscription_id):** routing keys per subscription, single-threaded consumer per partition. Highest throughput, most complex. Also over-engineered.

Record the choice and rationale in `DECISIONS.md` under Phase 8. If Phase 11+ surfaces throughput problems, revisit.

## Policies required this phase

**Mediation:**
- [ ] `usage.record.subscription_must_exist` — cross-service via SubscriptionClient
- [ ] `usage.record.subscription_must_be_active` — blocked → reject (block-on-exhaust at the edge)
- [ ] `usage.record.positive_quantity`
- [ ] `usage.record.valid_event_type` — must be one of `data`, `voice_minutes`, `sms`
- [ ] `usage.record.msisdn_belongs_to_subscription` — cross-service check

**Rating:**
- [ ] `rating.tariff_must_exist_for_offering`

## Events

**Published by Mediation:**
- `usage.recorded` (happy path)
- `usage.rejected` (blocked, unknown MSISDN, invalid quantity)

**Published by Rating:**
- `usage.rated`

**Consumed by Subscription (new, replaces Phase 6 test endpoint):**
- `usage.rated` → decrement balance (with `FOR UPDATE`) → maybe exhaust → maybe block

## Test strategy

Phase 4/5/6 lessons all apply. Phase 8 specific requirements:

### Required test files

**mediation/:**
- `test_usage_ingestion_api.py` — httpx tests for every endpoint, camelCase
- `test_usage_policies.py` — all 5 policies, negative cases
- `test_blocked_rejection.py` — blocked subscription → 422, no row in mediation.usage_event
- `test_mediation_cross_service_failures.py` — respx for Subscription 404/503

**rating/:**
- `test_rating_pure_function.py` — matrix over offerings, balances, usage types
- `test_rating_event_consumer.py` — usage.recorded → usage.rated

**Integration (at repo root `tests/integration/phase_08/`):**
- `test_usage_to_block_flow.py` — active subscription on PLAN_M, consume 30GB in chunks, verify block transition
- `test_block_then_vas_unblock.py` — blocked → VAS purchase → active → new usage accepted
- `test_concurrent_decrement_50.py` — 50 parallel usage events for same subscription, assert final balance is deterministic (no lost decrements)
- `test_end_to_end_latency.py` — POST /usage to subscription.exhausted event, assert p99 < 500ms

### Regression

- [ ] Phase 7 happy-path order still works end-to-end
- [ ] Phase 7 failure scenario 2 (eSIM release) still works
- [ ] Phase 6 concurrent subscription create still works

## ID generation

Sequences: `mediation.usage_event_id_seq`.

## Verification checklist

- [ ] `make up` brings up mediation and rating alongside previous services
- [ ] `POST /usage` for active PLAN_M subscription with 1000MB data → 201, event chain runs, balance decremented by 1000MB
- [ ] Repeat until balance < next usage → subscription transitions to blocked, next `POST /usage` returns 422 rule `usage.record.subscription_must_be_active`
- [ ] After block, `POST /vas-purchase` → active again → new `POST /usage` accepted
- [ ] `POST /usage` with negative quantity → 422 rule `usage.record.positive_quantity`
- [ ] `POST /usage` for unknown MSISDN → 422 rule `usage.record.subscription_must_exist`
- [ ] End-to-end latency POST /usage → subscription balance update < 500ms p99 (local)
- [ ] Concurrent `POST /usage` (50 parallel for same subscription) → all processed, final balance is deterministic, no lost decrements
- [ ] `audit.domain_event` shows full chain: `usage.recorded` → `usage.rated` → (on exhaustion) `subscription.exhausted` → `subscription.blocked`
- [ ] Phase 6 test endpoint is **removed or gated**: `curl -s -o /dev/null -w "%{http_code}" localhost:8006/subscription-api/v1/subscription/SUB-001/consume-for-test` returns 404 (if removed) or 403/501 (if gated and flag off)
- [ ] Phase 7 regression: happy-path order still completes, failure scenario 2 still releases eSIM
- [ ] `make test` all suites green
- [ ] `docker compose build --no-cache mediation rating` builds clean
- [ ] Campaign OS schemas untouched

## Out of scope

- CDR file ingestion (single-event POST only for v0.1)
- Real charging (pay-per-use, post-paid) — doctrine says no
- Rating rules engine — not needed for bundled prepaid
- Real-time usage streaming to dashboards — Phase 11+
- Usage aggregation tables — Metabase reads raw events for v0.1

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md` (schemas `mediation`), `TOOL_SURFACE.md`, `DECISIONS.md`, `phases/PHASE_06.md` (bundle.consume), and `phases/PHASE_08.md`.
>
> Before writing any code, produce a plan that includes:
>
> 1. **Mediation service layout** — clone Phase 5/6 pattern for `services/mediation/`.
>
> 2. **Rating service layout** — same, for `services/rating/`.
>
> 3. **Flow diagram** — POST /usage → enrich → persist → emit → Rating → emit → Subscription handler → balance update → possible block. Show exact events, routing keys, and payloads.
>
> 4. **Block-at-edge rule** — confirm Mediation rejects usage for blocked subscriptions at step 3 BEFORE persisting the row. This is non-negotiable doctrine.
>
> 5. **Concurrent decrement solution** — commit to Option A (`SELECT ... FOR UPDATE` per subscription balance row). Paste the exact repository method with the `with_for_update()` clause. Add a DECISIONS.md entry documenting the choice vs B and C.
>
> 6. **Phase 6 test endpoint removal plan** — confirm `POST /subscription/{id}/consume-for-test` is removed (preferred) or gated behind `BSS_ENABLE_TEST_ENDPOINTS=true` with default false. Delete any tests that relied on it; those are now covered by real usage-event tests.
>
> 7. **Rating function signature** — confirm `rate_usage(usage, tariff, balance)` is pure (no DB, no HTTP, no side effects). Paste the signature and test matrix (every offering × allowance type × usage quantity).
>
> 8. **Policy catalog** — all 6 policies with rule ID, module, cross-service dependency, negative-test case.
>
> 9. **Test strategy** — httpx tests for every endpoint, parametrized for state-dependent cases, respx mocks for cross-service failure paths, 50-parallel decrement test with deterministic final-balance assertion.
>
> 10. **Regression check plan** — confirm Phase 6 and Phase 7 tests still pass at end of phase.
>
> Wait for my approval before writing any code.
>
> After I approve, implement in this order:
> 1. `services/mediation/` — repositories, policies, services, routes, events
> 2. `services/rating/` — pure `rate_usage` function with unit tests first
> 3. Subscription event consumer for `usage.rated` with `FOR UPDATE` balance update
> 4. Remove (or gate) the Phase 6 test endpoint
> 5. Update `services/subscription/app/events/` to subscribe to `usage.rated`
> 6. Integration tests: usage → block → VAS → unblock → usage
> 7. Concurrent decrement test with 50 parallel events
> 8. Regression: Phase 7 order flow, Phase 7 scenario 2 eSIM release
> 9. `docker-compose.yml` — add mediation (8007) and rating (8008)
>
> Run full verification checklist. Do not commit.

## The trap

**The concurrent-decrement problem is the trap.** Two usage events arrive, both read balance=100, both compute new_balance=50, last write wins, you lost 50 units. The fix is `SELECT ... FOR UPDATE` in the consumer, serializing per-subscription. Don't let Claude Code skip this or use a naive `UPDATE ... SET balance = balance - ?` pattern — that works for simple numeric columns but not for the structured balance rows we have.

**Block-at-edge is doctrine, not "nice-to-have".** Mediation must reject usage for blocked subscriptions BEFORE persisting. If blocked usage gets into the pipeline, the audit trail lies. The test for this is non-negotiable.

**Remove the Phase 6 test endpoint.** If it ships to v0.1, anyone (or Claude Code in a future phase) can bypass Mediation's ingress checks and manipulate balances directly. That's how doctrine rots.

**Regression check Phase 7 scenario 2.** The eSIM release on failure test must still pass after Phase 8 changes. Phase 8 touches Subscription's event handling — make sure it doesn't break SOM's cleanup path by accident.
