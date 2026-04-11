# Phase 8 — Mediation + Rating (the usage flow)

## Goal

Close the loop from usage events back to bundle balance decrement and exhaustion. Mediation ingests, Rating consumes, Subscription decrements. By the end of this phase, `usage.simulate` causes real balance depletion and real blocking.

Shorter phase — mostly event wiring over domain logic that already exists.

## Deliverables

### Service: `services/mediation/` (port **8007**)

**Endpoints (TMF635):**
- `POST /tmf-api/usageManagement/v4/usage` — ingest a single usage event (primarily used by `usage.simulate` and by the scenario runner)
- `GET  /tmf-api/usageManagement/v4/usage?subscriptionId={id}&since={ts}&type={type}`
- `GET  /tmf-api/usageManagement/v4/usage/{id}`
- `GET /health`, `GET /ready`

**Flow:**
1. Receive usage event
2. Enrich: look up subscription by MSISDN (via bss-clients → subscription service). If no active subscription, store with `processing_error='no_active_subscription'` and return 422.
3. Persist to `mediation.usage_event` with `processed=false`
4. Emit `usage.recorded` with full enriched payload
5. Return 201

**Blocked-subscription rule:** if subscription is in `blocked` state, Mediation REJECTS the usage at step 2 with `processing_error='subscription_blocked'`. This is the "block-on-exhaust" doctrine in action at the network edge — no usage is even recorded for blocked subs.

### Service: `services/rating/` (port **8008**)

**Endpoints:** minimal, mostly event-driven
- `GET /rating-api/v1/tariff/{offering_id}` — debug/inspection
- `POST /rating-api/v1/rate-test` — test endpoint: take a usage event payload, return what the rating would be, don't persist
- `GET /health`, `GET /ready`

**Core: tariff lookup + pure rating function** (`app/domain/rating.py`):

```python
def rate_usage(
    usage: UsageEvent,
    tariff: Tariff,
    balance: BundleBalance
) -> RatingResult:
    """
    Pure function. Returns (consumed_quantity, charge_amount, allowance_type).
    For bundled prepaid v0.1: charge_amount is always 0 (bundle is prepaid).
    consumed_quantity == usage quantity (no tiering, no time-of-day rules).
    """
```

**Why rating is trivial in v0.1:** bundled prepaid means there's no per-unit charging. Usage just decrements the bundle. Rating becomes a unit-conversion + allowance-mapping function. This is the doctrine simplification paying off.

The rating service is still a separate service because (a) architecturally correct, (b) future rating rules can live here without touching Subscription.

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
        # Guard: shouldn't happen because Mediation rejects at ingress, but belt-and-braces
        return
    new_balance = bundle.consume(
        balance=get_balance(subscription.id, event.allowance_type),
        quantity=event.consumed_quantity,
        allowance_type=event.allowance_type
    )
    await repo.update_balance(new_balance)
    if bundle.is_exhausted([new_balance]):
        await transition(subscription, "exhaust")
        # Automatically publishes subscription.exhausted and subscription.blocked
```

Remove the test-only endpoint or hide it behind `BSS_ENABLE_TEST_ENDPOINTS=true`.

## Policies required this phase

**Mediation:**
- [ ] `usage.record.subscription_must_exist`
- [ ] `usage.record.subscription_must_be_active` — blocked → reject
- [ ] `usage.record.positive_quantity`
- [ ] `usage.record.valid_event_type`
- [ ] `usage.record.msisdn_belongs_to_subscription`

**Rating:**
- [ ] `rating.tariff_must_exist_for_offering`

## Events

**Published by Mediation:**
- `usage.recorded`
- `usage.rejected`

**Published by Rating:**
- `usage.rated`

**Consumed by Subscription (new):**
- `usage.rated` → decrement balance → maybe exhaust → maybe block

## Verification checklist

- [ ] `make up` brings up mediation and rating alongside previous services
- [ ] `POST /usage` for an active subscription on PLAN_M with 1000MB data → 201, event chain runs, balance decremented by 1000MB
- [ ] Repeat until balance < next usage → subscription transitions to blocked, next `POST /usage` is rejected with 422 reason `subscription_blocked`
- [ ] After block, `POST /vas-purchase` → active again → new `POST /usage` accepted
- [ ] `POST /usage` with negative quantity → 422
- [ ] `POST /usage` for unknown MSISDN → 422
- [ ] End-to-end latency from `POST /usage` to subscription balance update < 500ms p99 in local test
- [ ] Concurrent `POST /usage` (50 parallel) → all processed, no lost decrements (final balance is deterministic)
- [ ] `audit.domain_event` shows the full chain: `usage.recorded` → `usage.rated` → (possibly) `subscription.exhausted` → `subscription.blocked`
- [ ] `make mediation-test`, `make rating-test` pass
- [ ] Regression: Phase 7 happy-path order still works end-to-end

## Out of scope

- CDR file ingestion (single-event POST only for v0.1)
- Real charging (pay-per-use, post-paid) — doctrine says no
- Rating rules engine — not needed for bundled prepaid
- Real-time usage streaming to dashboards — Phase 11+
- Usage aggregation tables — Metabase reads raw events for v0.1

## Session prompt

> Read `CLAUDE.md`, `DATA_MODEL.md`, `phases/PHASE_06.md`, `phases/PHASE_08.md`.
>
> Before coding, confirm:
> 1. Rating is a pure function over (usage, tariff, balance) — no side effects
> 2. Mediation rejects at ingress for blocked subscriptions
> 3. The concurrent-decrement test will use optimistic locking or serializable isolation (pick one and document it in DECISIONS.md)
> 4. The Phase 6 test-only endpoint is removed or gated
>
> Wait for approval. Implement in this order: mediation → rating → subscription consumer wiring → end-to-end tests.

## The discipline

**The concurrent-decrement problem is the trap.** Two usage events arrive, both read balance=100, both compute new_balance=50, last write wins, you lost 50 units. Solutions:
- **Option A:** `SELECT ... FOR UPDATE` in the consumer, serialize per-subscription.
- **Option B:** Optimistic locking with a version column, retry on conflict.
- **Option C:** Single-threaded consumer per subscription (RabbitMQ routing by subscription_id).

Recommend **Option A** for v0.1 — simplest, correct, good enough at BSS-CLI's scale. Document the choice in DECISIONS.md.
