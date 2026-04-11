# Phase 6 — Subscription Service + Bundle Balance

> **The operational heart.** State machine + bundle math + events + concurrency. Take it slow. Write the state table before any code. Test pure functions before anything else.

## Goal

Subscription service that owns lifecycle, bundle balance, VAS top-up, renewal, termination. Note: in v3, subscription creation is driven by SOM (Phase 7) after a service order completes, with MSISDN and eSIM already reserved at that point. For this phase we test via direct `POST /subscription` — the SOM integration happens in Phase 7.

## Deliverables

### Service: `services/subscription/` (port **8006**)

Clone the Phase 5 Payment structure. Stateful with a non-trivial FSM.

### Endpoints

- `POST  /subscription-api/v1/subscription` — called by SOM in Phase 7, called by tests directly for now
- `GET   /subscription-api/v1/subscription/{id}`
- `GET   /subscription-api/v1/subscription?customerId={id}`
- `GET   /subscription-api/v1/subscription/by-msisdn/{msisdn}`
- `GET   /subscription-api/v1/subscription/{id}/balance`
- `POST  /subscription-api/v1/subscription/{id}/vas-purchase`
- `POST  /subscription-api/v1/subscription/{id}/renew` — manual renewal trigger
- `POST  /subscription-api/v1/subscription/{id}/terminate` — destructive
- `POST  /subscription-api/v1/subscription/{id}/consume-for-test` — **Phase 6 only**, gated behind `BSS_ENABLE_TEST_ENDPOINTS=true`, removed in Phase 8
- `GET /health`, `GET /ready`

### State machine — must go into DECISIONS.md before any code

```
States: pending, active, blocked, terminated

Transitions:
  pending  --activate-->     active      guard: payment.charge succeeds
                                         action: init_balance
  pending  --fail-activate-> terminated  guard: payment.charge fails
                                         action: release_msisdn, release_esim
  active   --exhaust-->      blocked     trigger: primary allowance <= 0
                                         action: emit exhausted, emit blocked
  blocked  --top_up-->       active      guard: vas_payment succeeds
                                         action: add_allowance, emit vas_purchased, emit unblocked
  active   --top_up-->       active      action: add_allowance, emit vas_purchased
  active   --renew-->        active      guard: renewal_payment succeeds
                                         action: reset_balance, advance_period
  active   --renew_fail-->   blocked     guard: renewal_payment fails
                                         action: emit renew_failed, emit blocked
  active   --terminate-->    terminated  action: release_msisdn, recycle_esim, emit terminated
  blocked  --terminate-->    terminated  action: release_msisdn, recycle_esim, emit terminated

Terminal states: terminated
```

**Non-negotiable.** Claude Code must paste this table into `DECISIONS.md` under a Phase 6 section and pause for approval before writing any state machine code. If Claude Code says "the code is clearer than a table" — stop it. The table is the spec. The code is the implementation.

### Bundle balance domain logic — `app/domain/bundle.py`

**Pure functions, fully unit-tested BEFORE anything else in this phase.**

```python
def consume(balance: BundleBalance, quantity: int, allowance_type: str) -> BundleBalance:
    """Decrement. Returns new balance. Pure. Never mutates input."""

def is_exhausted(balances: list[BundleBalance], primary_type: str) -> bool:
    """True if the primary allowance type is at zero. Voice/SMS unlimited don't block."""

def add_allowance(balance: BundleBalance, allowance_type: str, quantity: int) -> BundleBalance:
    """Top up. Returns new balance. Pure."""

def reset_for_new_period(
    balances: list[BundleBalance],
    offering: ProductOffering,
    period_start: datetime,
    period_length_days: int,
) -> list[BundleBalance]:
    """Renewal: reset to plan defaults, advance period. Pure."""

def primary_allowance_type(offering: ProductOffering) -> str:
    """For prepaid mobile bundles, data is the primary. Always 'data' in v0.1."""
```

Exhaustion is defined on the **primary allowance type only**. Running out of SMS (which is unlimited on M/L anyway) doesn't block the subscription. On plan S, running out of SMS also doesn't block — only data does. Deliberate simplification for v0.1.

### MSISDN + eSIM allocation

In v3, subscription creation is driven by SOM (Phase 7). SOM has already reserved both an MSISDN and an eSIM profile via `bss-clients.InventoryClient` calls to CRM's Inventory sub-domain. By the time Subscription receives the create call, `msisdn` and `iccid` are already in the request body — Subscription just persists the binding and calls Inventory to mark both as `assigned`.

```python
# services/subscription/app/services/subscription_service.py
async def create(
    customer_id: str,
    offering_id: str,
    msisdn: str,
    iccid: str,
    payment_method_id: str,
):
    # Policies: requires_customer, requires_payment_success, msisdn_and_esim_reserved
    payment = await payment_client.charge(
        method_id=payment_method_id,
        amount=offering.recurring_charge,
        currency="SGD",
    )
    if payment.status != "approved":
        await inventory_client.release_msisdn(msisdn)
        await inventory_client.release_esim(iccid)
        raise PolicyViolation(
            rule="subscription.create.requires_payment_success",
            ...,
        )

    subscription = await repo.create(
        customer_id=customer_id,
        offering_id=offering_id,
        msisdn=msisdn,
        iccid=iccid,
        state="pending",
    )
    await init_bundle_balance(subscription, offering_id)

    # Mark inventory as assigned (idempotent)
    await inventory_client.assign_msisdn(msisdn, subscription.id)
    await inventory_client.assign_esim(iccid, subscription.id)

    await transition(subscription, "activate")
    # emits subscription.activated
```

**On termination:**

```python
await inventory_client.release_msisdn(msisdn)   # quarantine for 90d (stubbed as 'available' in v0.1)
await inventory_client.recycle_esim(iccid)      # status='recycled'
```

Both MSISDN and eSIM are released in the same terminate flow. Subscription **never** touches the inventory tables directly — always via `bss-clients` to maintain the schema boundary.

### Cross-service calls — add `SubscriptionClient` to `bss-clients`

Phase 5 scaffolded `bss-clients/payment.py` as a placeholder. Phase 6 adds `bss-clients/subscription.py` with these methods:

- `get(subscription_id)` → Subscription
- `list_for_customer(customer_id)` → list[Subscription]
- `get_by_msisdn(msisdn)` → Subscription
- `purchase_vas(subscription_id, vas_offering_id)` → Subscription
- `terminate(subscription_id)` → Subscription

This client is consumed in Phase 6 by CRM's `customer.close.no_active_subscriptions` policy, which was a stub in Phase 4 and becomes real here.

### Events published

- `subscription.activated`
- `subscription.exhausted`
- `subscription.blocked`
- `subscription.unblocked`
- `subscription.renewed`
- `subscription.renew_failed`
- `subscription.terminated`
- `subscription.vas_purchased`

### Events consumed (placeholder for Phase 8)

- `usage.rated` (from Rating, Phase 8) → decrement balance → maybe exhaust

Phase 6 stubs this by implementing the gated test endpoint `POST /subscription/{id}/consume-for-test` which simulates rated usage arriving. This endpoint is **removed or gated behind `BSS_ENABLE_TEST_ENDPOINTS=true` in Phase 8**.

### Concurrency — the MSISDN double-allocation trap

Two concurrent `POST /subscription` calls for the same plan with no MSISDN preference can race on MSISDN reservation. Phase 4's inventory sub-domain uses `SELECT ... FOR UPDATE SKIP LOCKED` for MSISDN pool reservation, which is the correct primitive. Phase 6's test suite must prove this works:

```python
async def test_concurrent_subscription_creates_no_double_allocation():
    results = await asyncio.gather(*[
        client.post("/subscription", json={"customerId": f"CUST-0{i:03d}", "offeringId": "PLAN_M", ...})
        for i in range(10)
    ])
    msisdns = {r.json()["msisdn"] for r in results if r.status_code == 201}
    assert len(msisdns) == 10  # all distinct
```

## Policies required this phase

- [ ] `subscription.create.requires_customer` — cross-service via CRMClient
- [ ] `subscription.create.requires_payment_success` — cross-service via PaymentClient
- [ ] `subscription.create.msisdn_and_esim_reserved` — both `msisdn` and `iccid` must be in `reserved` state for this customer's order, not `assigned`/`available`
- [ ] `subscription.vas_purchase.requires_active_cof` — cross-service via PaymentClient
- [ ] `subscription.vas_purchase.vas_offering_sellable` — cross-service via CatalogClient
- [ ] `subscription.vas_purchase.not_if_terminated`
- [ ] `subscription.renew.only_if_active_or_blocked`
- [ ] `subscription.terminate.releases_msisdn` — encoded as guaranteed side-effect in terminate handler
- [ ] `subscription.terminate.recycles_esim` — encoded as guaranteed side-effect in terminate handler
- [ ] `subscription.terminate.cancels_pending_vas`

Also, the **`customer.close.no_active_subscriptions` stub in Phase 4 becomes real in this phase** — CRM's policy now calls `bss-clients.SubscriptionClient.list_for_customer(customer_id)` and rejects if any subscription is in `pending`, `active`, or `blocked` state.

## Test strategy

Phase 4 lessons apply — `httpx.AsyncClient` tests for every router endpoint, DB sequences for IDs, parametrized state machine transitions. Plus new requirements for Phase 6 specifically:

### Required test files

- `test_bundle.py` — pure function tests. **100% branch coverage.** Use Hypothesis property tests for `consume` invariants (never negative, never exceeds max, add/consume round-trips to identity for same quantity).
- `test_state_machine.py` — parametrized over the transitions table from DECISIONS.md. Every transition has a test. Forbidden transitions must raise `PolicyViolation`.
- `test_subscription_api.py` — httpx tests for every router endpoint with camelCase JSON bodies.
- `test_concurrent_create.py` — 10 concurrent POSTs, assert 10 distinct MSISDNs, 10 distinct ICCIDs, zero PK collisions.
- `test_vas_purchase.py` — happy path (active), blocked→active, declined payment (422), terminated subscription (422).
- `test_terminate.py` — happy path, verify MSISDN release, verify eSIM recycle, verify events emitted.
- `test_customer_close_integration.py` — integration test from CRM's side: attempt `customer.close` on a customer with active subscription → expect 422 with rule `customer.close.no_active_subscriptions`. This proves the Phase 4 stub is now real.
- `test_cross_service_mocks.py` — respx-mocked Payment and Catalog for error paths.
- `test_id_sequences.py` — create two subscriptions, simulate app restart, create a third, assert no PK collision.

### Cross-service test strategy (Phase 5 pattern)

- **Happy path: real containers.** Payment, Catalog, CRM must all be up. Tests exercise the full wire.
- **Error paths: `respx`.** Mock Payment/Catalog/CRM returning 404, 422, 503, malformed responses.

## ID generation

Postgres sequences for `SUB-xxx`. Same rule as Phase 5.

```sql
CREATE SEQUENCE subscription.subscription_id_seq;
```

## Verification checklist

- [ ] State machine table is in `DECISIONS.md` and matches the code
- [ ] `test_bundle.py` has 100% branch coverage on all pure functions (check via coverage.py)
- [ ] `POST /subscription` with valid customer + COF + reserved msisdn/iccid → allocates balance, transitions to active, emits `subscription.activated`
- [ ] Concurrent POSTs (10 parallel with distinct customers) → all succeed, 10 distinct MSISDNs, 10 distinct ICCIDs
- [ ] `POST /subscription/{id}/consume-for-test` decrementing past zero → transitions to blocked, emits `exhausted` then `blocked`
- [ ] `POST /subscription/{id}/vas-purchase` on blocked → charge succeeds → back to active, emits `vas_purchased` and `unblocked`
- [ ] `POST /subscription/{id}/vas-purchase` with declined payment → 422, rule `subscription.vas_purchase.requires_active_cof`, no state change, no inventory mutation
- [ ] `POST /subscription/{id}/terminate` → emits `terminated`, Inventory shows MSISDN back to `available` (stubbed quarantine), eSIM in `recycled`
- [ ] `POST /customer/{id}/close` on a customer with active subscription → 422 rule `customer.close.no_active_subscriptions` (Phase 4 stub now real)
- [ ] Every transition writes a row to `subscription.subscription_state_history`
- [ ] Every transition writes a row to `audit.domain_event` in the same transaction
- [ ] RabbitMQ management UI shows all events flowing to the `bss.events` exchange with the right routing keys
- [ ] `make test` — catalog + crm + payment + subscription all green, no regression
- [ ] `docker compose logs subscription` — no PII leakage (grep for any NRIC-like patterns from seed data)
- [ ] `docker compose build --no-cache subscription` builds clean
- [ ] Campaign OS schemas untouched
- [ ] ID counter survives restart test

## Out of scope

- Renewal scheduler (manual `/renew` endpoint for now; scheduler is Phase 11)
- VAS expiry enforcement (24h day pass — Phase 11)
- Real integration with Rating (Phase 8)
- Real integration with SOM (Phase 7)
- Proration, dunning, grace periods (doctrine: NEVER)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `TOOL_SURFACE.md`, `DECISIONS.md`, and `phases/PHASE_06.md`. Read `services/payment/` as the service pattern reference. Read the Phase 4 `DECISIONS.md` entries on API-level test coverage, state machine parametrization, and ID generation surviving restart. Read the Phase 5 entry on hybrid cross-service test strategy.
>
> Before writing any code, produce a plan that includes:
>
> 1. **State machine table** — paste the full transitions table into `DECISIONS.md` under a new Phase 6 entry. Columns: From State, Trigger, To State, Guard, Action. Every transition explicit. Terminal states marked. Wait for my explicit approval of this table before continuing. Do not write state machine code until approved.
>
> 2. **`bundle.py` function signatures and test cases** — paste the full module signature and for each function, list the test cases you will write. Include property-test ideas (Hypothesis) for `consume` invariants. Confirm pure functions, no DB, no side effects.
>
> 3. **Policy catalog** — all 10 policies with rule ID, module, cross-service dependency if any, and negative-test case.
>
> 4. **Event payload schemas** — for each of the 8 events published, paste the JSON schema (field names, types, required flags). Confirm these match the `bss-events` package's event model.
>
> 5. **Cross-service calls** — confirm `SubscriptionClient` is added to `bss-clients/`. Confirm Payment, Catalog, CRM clients are consumed (not direct DB queries). Paste the list of outbound calls with their purposes.
>
> 6. **Concurrent MSISDN test design** — paste the exact test that proves `SELECT FOR UPDATE SKIP LOCKED` in CRM's inventory sub-domain prevents double-allocation when Subscription makes 10 parallel creates.
>
> 7. **Test endpoint gating** — confirm `POST /subscription/{id}/consume-for-test` is guarded by an env flag and will be removed in Phase 8. Document this in DECISIONS.md as a "to be removed" item.
>
> 8. **ID generation** — Postgres sequence for `SUB-xxx`, not counters.
>
> 9. **Test coverage** — confirm every router endpoint has at least one `httpx.AsyncClient` test with camelCase JSON (Phase 4 lesson). Confirm state machine transitions are parametrized per the Phase 4 lesson. Confirm `test_bundle.py` has 100% branch coverage.
>
> Wait for my approval before writing any code.
>
> After I approve, implement bottom-up:
> 1. `packages/bss-clients/bss_clients/subscription.py` — new client
> 2. `services/subscription/app/domain/bundle.py` — pure functions
> 3. `services/subscription/tests/test_bundle.py` — 100% branch coverage BEFORE moving on
> 4. `services/subscription/app/domain/state_machine.py` — pure state machine
> 5. `services/subscription/tests/test_state_machine.py` — parametrized over all transitions
> 6. `services/subscription/app/repositories/` — subscription, balance, state_history
> 7. `services/subscription/app/policies/` — all 10 policies
> 8. `services/subscription/app/services/subscription_service.py` — orchestration
> 9. `services/subscription/app/schemas/` — internal DTOs
> 10. `services/subscription/app/api/` — routers, no business logic
> 11. `services/subscription/app/events/publisher.py`
> 12. Tests: API (httpx), concurrent create, cross-service (respx), customer_close integration, ID sequence restart
> 13. Update `services/crm/app/policies/customer.py` — wire real check for `customer.close.no_active_subscriptions` via `SubscriptionClient`
> 14. Alembic migration for sequence
> 15. `docker-compose.yml` — add subscription on port 8006
>
> Do not move on from bundle.py until its tests are green. Run full verification checklist when done. Do not commit.

## The trap

**Test pure functions before anything else.** If `consume()` is wrong, the entire BSS is wrong. Spend 30 minutes on Hypothesis property tests for the bundle functions and thank yourself later.

**Don't skip the state table.** If Claude Code says "the code is clearer than a table" — stop it. The table is the spec. The code is the implementation. Spec first, always.

**Don't let Claude Code leak inventory access.** Subscription calls `bss-clients.InventoryClient` (hosted on CRM, port 8002). Direct `SELECT ... FROM inventory.msisdn_pool` in Subscription's code is a schema boundary violation. Grep check: `grep -r "inventory\." services/subscription/app/` returns zero direct schema references.

**Don't let the test endpoint become permanent.** `POST /consume-for-test` is Phase 6 scaffolding only. It must be env-gated. Phase 8 removes it. If it ships to v0.1 without a gate, usage simulation can bypass Mediation's ingress rules and the block-on-exhaust doctrine breaks silently.

**Don't skip the concurrent allocation test.** Inventory reservation uses `SELECT FOR UPDATE SKIP LOCKED`. If that doesn't work under real concurrency, the entire multi-tenant story falls apart. The 10-parallel-create test is the proof.
