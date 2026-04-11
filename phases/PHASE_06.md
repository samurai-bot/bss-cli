# Phase 6 — Subscription Service + Bundle Balance

> **The operational heart.** State machine + bundle math + events. Take it slow. Write the state table before any code.

## Goal

Subscription service that owns lifecycle, bundle balance, VAS top-up, renewal, termination. Note: in v2, subscription is **created by SOM** (Phase 7) after a service order completes, not directly by COM. For this phase we test it by calling `POST /subscription` directly — the SOM integration happens in Phase 7.

## Deliverables

### Service: `services/subscription/` (port **8006**)

Follows the Phase 3/4/5 pattern. Stateful with a non-trivial FSM.

### Endpoints

- `POST  /subscription-api/v1/subscription` — activate (called by SOM in Phase 7, called by tests directly for now)
- `GET   /subscription-api/v1/subscription/{id}`
- `GET   /subscription-api/v1/subscription?customerId={id}`
- `GET   /subscription-api/v1/subscription/by-msisdn/{msisdn}`
- `GET   /subscription-api/v1/subscription/{id}/balance`
- `POST  /subscription-api/v1/subscription/{id}/vas-purchase`
- `POST  /subscription-api/v1/subscription/{id}/renew` — manual renewal trigger
- `POST  /subscription-api/v1/subscription/{id}/terminate` — destructive
- `GET /health`, `GET /ready`

### State machine

```
States: pending, active, blocked, terminated

Transitions:
  pending  --activate-->    active      [guard: payment.charge succeeds]
                                         [action: allocate_msisdn, init_balance]
  pending  --fail-activate-> terminated [guard: payment.charge fails]
  active   --exhaust-->     blocked     [trigger: balance.remaining <= 0 after consume]
  blocked  --top_up-->      active      [guard: vas_payment succeeds]
                                         [action: add_allowance]
  active   --top_up-->      active      [action: add_allowance]
  active   --renew-->       active      [guard: renewal_payment succeeds]
                                         [action: reset_balance, advance_period]
  active   --renew_fail-->  blocked     [guard: renewal_payment fails]
  active   --terminate-->   terminated  [action: release_msisdn, terminate_services]
  blocked  --terminate-->   terminated  [action: release_msisdn, terminate_services]
```

**Fill this table into DECISIONS.md before coding.** Claude Code must pause for approval after drafting it.

### Bundle balance domain logic

`app/domain/bundle.py` — pure functions, fully unit-tested BEFORE anything else in this phase:

```python
def consume(balance: BundleBalance, quantity: int, allowance_type: str) -> BundleBalance:
    """Decrement. Returns new balance. Pure."""

def is_exhausted(balances: list[BundleBalance]) -> bool:
    """True if the primary allowance type is at zero. Voice/SMS unlimited don't block."""

def add_allowance(balance: BundleBalance, allowance_type: str, quantity: int) -> BundleBalance:
    """Top up. Returns new balance."""

def reset_for_new_period(
    balances: list[BundleBalance],
    offering: ProductOffering,
    period_start: datetime,
    period_length_days: int
) -> list[BundleBalance]:
    """Renewal: reset to plan defaults, advance period."""

def primary_allowance_type(offering: ProductOffering) -> str:
    """For prepaid mobile bundles, data is the primary. Always 'data' in v0.1."""
```

Exhaustion is defined on the **primary allowance type only**. Running out of SMS (which is unlimited on M/L anyway) doesn't block the subscription. On plan S, running out of SMS also doesn't block — only data does. This is a deliberate simplification for v0.1.

### MSISDN + eSIM allocation

In v3, subscription creation is driven by SOM (Phase 7) which has already reserved both an MSISDN and an eSIM profile via bss-clients calls to the CRM service's Inventory sub-domain. By the time Subscription creates the subscription row, the `msisdn` and `iccid` are already known — Subscription just persists the binding and calls Inventory to mark both as `assigned`.

```python
# On subscription creation (called by SOM via bss-clients):
async def create(customer_id, offering_id, msisdn, iccid, payment_method_id):
    # Policy: requires_customer, requires_payment_success, msisdn_and_esim_reserved
    payment = await payment_client.charge(...)
    if payment.status != "approved":
        raise PolicyViolation(rule="subscription.create.requires_payment_success", ...)
    
    subscription = await repo.create(
        customer_id=customer_id,
        offering_id=offering_id,
        msisdn=msisdn,
        iccid=iccid,
        state="pending"
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
await inventory_client.release_msisdn(msisdn)   # → status='quarantine' for 90 days
await inventory_client.recycle_esim(iccid)      # → status='recycled'
```

Both MSISDN and eSIM are released in the same terminate flow. Subscription never touches the inventory tables directly — always via bss-clients to maintain the schema boundary.

### Events published

- `subscription.activated`
- `subscription.exhausted`
- `subscription.blocked`
- `subscription.unblocked`
- `subscription.renewed`
- `subscription.terminated`
- `subscription.vas_purchased`

### Events consumed (this phase)

- `usage.rated` (from Rating service, Phase 8) → decrement balance → maybe exhaust

For this phase, since Rating doesn't exist yet, implement a test-only endpoint `POST /subscription/{id}/consume-for-test` that simulates rated usage arriving. Remove or gate it behind an env flag in Phase 8.

## Policies required this phase

- [ ] `subscription.create.requires_customer`
- [ ] `subscription.create.requires_payment_success`
- [ ] `subscription.create.msisdn_available`
- [ ] `subscription.vas_purchase.requires_active_cof`
- [ ] `subscription.vas_purchase.vas_offering_sellable`
- [ ] `subscription.vas_purchase.not_if_terminated`
- [ ] `subscription.renew.only_if_active_or_blocked`
- [ ] `subscription.terminate.releases_msisdn` (action, not check, but encoded as a guaranteed side-effect)
- [ ] `subscription.terminate.cancels_pending_vas`

Also, the `customer.close.no_active_subscriptions` stub from Phase 4 becomes real in this phase — CRM's policy now calls `bss-clients.SubscriptionClient.list_for_customer(customer_id)` to check.

## Verification checklist

- [ ] Bundle pure functions have 100% branch coverage (unit tests, no DB)
- [ ] State machine table is in `DECISIONS.md` and matches the code
- [ ] `POST /subscription` with valid customer + COF → allocates MSISDN, creates balance, emits `subscription.activated`
- [ ] Concurrent POSTs don't double-allocate MSISDNs (test with `asyncio.gather` of 10 concurrent requests)
- [ ] `POST /subscription/{id}/consume-for-test` decrementing past zero → transitions to blocked, emits `exhausted` and `blocked`
- [ ] `POST /subscription/{id}/vas-purchase` on blocked subscription → charge succeeds → back to active, emits `vas_purchased` and `unblocked`
- [ ] `POST /subscription/{id}/vas-purchase` with declined payment → 422 policy violation, no state change
- [ ] `POST /subscription/{id}/terminate` → MSISDN returns to `available`, emits `terminated`
- [ ] `customer.close` on a customer with active subscription → 422 (policy now wired through)
- [ ] Every transition logs to `subscription_state_history` and `audit.domain_event`
- [ ] RabbitMQ management UI shows all events flowing to the `bss.events` exchange
- [ ] `make subscription-test` passes

## Out of scope

- Renewal scheduler (manual `/renew` endpoint for now; scheduler in Phase 11)
- VAS expiry enforcement (24h day pass — Phase 11)
- Real integration with Rating (Phase 8)
- Real integration with SOM (Phase 7)
- Proration, dunning, grace periods (doctrine: NEVER)

## Session prompt

> Read `CLAUDE.md`, `DATA_MODEL.md`, `phases/PHASE_04.md`, `phases/PHASE_05.md`, `phases/PHASE_06.md`.
>
> This is the hardest phase so far. Before writing any code:
> 1. Fill in the state machine table in `DECISIONS.md`
> 2. List the bundle.py function signatures and the test cases for each
> 3. List every policy and its test cases
> 4. List every event published with its payload schema
>
> Wait for approval. Then implement bottom-up: bundle.py + unit tests FIRST, then state machine + unit tests, then repositories, then policies, then services, then routers, then integration tests.
>
> Do not move on from bundle.py until its tests are green.

## The discipline

**Test pure functions before anything else.** If `consume()` is wrong, the entire BSS is wrong. Spend 30 minutes on Hypothesis property tests for the bundle functions and thank yourself later.

**Don't skip the state table.** If Claude Code says "the code is clearer than a table" — stop it. The table is the spec. The code is the implementation. Spec first, always.
