# Phase 7 — COM + SOM + Provisioning Simulator (with eSIM)

> **The most ambitious phase.** Three services, two state machines, one simulator, eSIM integration, and an event-driven decomposition flow. Budget 4-5 hours. **If running over 5 hours, split into 7a (provisioning-sim + SOM) and 7b (COM).** Better two clean phases than one muddled one.

## Goal

Three new services implementing the full order-to-activation flow, including eSIM profile reservation and activation code delivery.

1. **COM** (TMF622) — customer-facing order
2. **SOM** (TMF641 + TMF638) — decomposes commercial order into service orders, tracks CFS/RFS/Resource lifecycle, reserves MSISDN + eSIM
3. **Provisioning Simulator** — stands in for HLR/PCRF/OCS/SM-DP+, configurable fault injection

By end of phase: placing a commercial order triggers SOM, which reserves an MSISDN + eSIM profile via `bss-clients` to CRM's inventory and emits provisioning tasks. The simulator completes tasks (including `ESIM_PROFILE_PREPARE`). Flow returns through SOM → COM → Subscription. End-to-end activation works, customer receives an LPA activation code.

## Deliverables

### Service 1: `services/com/` (port **8004**)

Clone the Phase 5/6 pattern. Stateful with order FSM.

**Endpoints (TMF622):**
- `POST   /tmf-api/productOrderingManagement/v4/productOrder`
- `GET    /tmf-api/productOrderingManagement/v4/productOrder`
- `GET    /tmf-api/productOrderingManagement/v4/productOrder/{id}`
- `PATCH  /tmf-api/productOrderingManagement/v4/productOrder/{id}`
- `POST   /tmf-api/productOrderingManagement/v4/productOrder/{id}/cancel` — destructive
- `GET /health`, `GET /ready`

**Order state machine — goes into DECISIONS.md before coding:**

```
States: acknowledged, in_progress, completed, failed, cancelled

Transitions:
  acknowledged --start-->      in_progress   action: emit order.in_progress
  acknowledged --cancel-->     cancelled     action: emit order.cancelled
  in_progress  --cancel-->     cancelled     guard: som_not_started
                                              action: emit order.cancelled
  in_progress  --complete-->   completed     trigger: service_order.completed
                                              action: call subscription.create
  in_progress  --fail-->       failed        trigger: service_order.failed
                                              action: release_resources, emit order.failed

Terminal: completed, failed, cancelled
```

**Flow:**
1. `POST /productOrder` → policies (customer exists, has COF, has KYC if enforced, offering sellable) → create order in `acknowledged` → emit `order.acknowledged`
2. Transition to `in_progress` → emit `order.in_progress`
3. Consume `service_order.completed` → transition to `completed` → call `subscription-api` to create subscription (passing `msisdn` + `iccid` from the service order's characteristics)
4. Consume `service_order.failed` → transition to `failed` → emit `order.failed` → trigger cleanup (release MSISDN + eSIM via `bss-clients.InventoryClient`)

### Service 2: `services/som/` (port **8005**)

**Endpoints (TMF641 + TMF638 read):**
- `POST   /tmf-api/serviceOrderingManagement/v4/serviceOrder` — internal
- `GET    /tmf-api/serviceOrderingManagement/v4/serviceOrder/{id}`
- `GET    /tmf-api/serviceOrderingManagement/v4/serviceOrder?commercialOrderId={id}`
- `GET    /tmf-api/serviceInventoryManagement/v4/service/{id}`
- `GET    /tmf-api/serviceInventoryManagement/v4/service?subscriptionId={id}`
- `GET /health`, `GET /ready`

**Service state machine — also in DECISIONS.md before coding:**

```
States: feasibility_checked, designed, reserved, activated, failed, terminated

Transitions:
  feasibility_checked --design-->    designed    (v0.1: feasibility is a no-op, skip straight)
  designed            --reserve-->   reserved    action: reserve MSISDN + eSIM via bss-clients
  reserved            --activate-->  activated   guard: all_rfs_activated AND esim_prepared
                                                  action: emit service.activated
  designed            --fail-->      failed      action: release any reserved resources
  reserved            --fail-->      failed      action: release msisdn, release esim
  activated           --terminate--> terminated  action: release msisdn, recycle esim
```

CFS can only transition to `activated` once **all** its RFS are activated AND `ESIM_PROFILE_PREPARE` has completed. Enforced by policy `service.activate.requires_all_rfs_activated_and_esim_prepared`.

**Decomposition logic** (`app/domain/decomposition.py`) — pure function:

```python
@dataclass
class DecompositionPlan:
    cfs: ServiceCreation
    rfs: list[ServiceCreation]
    resources: list[ResourceReservation]   # MSISDN + eSIM
    provisioning_tasks: list[TaskCreation]

def decompose(order: ProductOrder, mapping: ProductToServiceMapping) -> DecompositionPlan:
    """
    PLAN_x → CFS_MobileBroadband
              ├── RFS_DataBearer   (needs MSISDN, eSIM)
              ├── RFS_VoiceBearer  (needs MSISDN)
              └── Resources: MSISDN (1), eSIM profile (1)
    """
    return DecompositionPlan(
        cfs=ServiceCreation(spec_id="SSPEC_CFS_MOBILE_BROADBAND", type="CFS"),
        rfs=[
            ServiceCreation(spec_id="SSPEC_RFS_DATA_BEARER", type="RFS", parent="__cfs__"),
            ServiceCreation(spec_id="SSPEC_RFS_VOICE_BEARER", type="RFS", parent="__cfs__"),
        ],
        resources=[
            ResourceReservation(type="MSISDN", preference=order.msisdn_preference),
            ResourceReservation(type="ESIM_PROFILE"),
        ],
        provisioning_tasks=[
            TaskCreation(type="ESIM_PROFILE_PREPARE", target="CFS"),
            TaskCreation(type="HLR_PROVISION",       target="RFS_VOICE"),
            TaskCreation(type="HLR_PROVISION",       target="RFS_DATA"),
            TaskCreation(type="PCRF_POLICY_PUSH",    target="RFS_DATA"),
            TaskCreation(type="OCS_BALANCE_INIT",    target="CFS"),
        ],
    )
```

**Resource reservation via `bss-clients` — NOT direct DB access:**

```python
async def reserve_resources(order, plan):
    async with inventory_client() as inv:
        msisdn = await inv.reserve_msisdn(preference=order.msisdn_preference)
        esim = await inv.reserve_esim()
        await inv.assign_msisdn_to_esim(iccid=esim.iccid, msisdn=msisdn.msisdn)
    return {
        "msisdn": msisdn.msisdn,
        "iccid": esim.iccid,
        "activation_code": esim.activation_code,
    }
```

The MSISDN+eSIM pairing is stored in the CFS service's `characteristics` JSONB:

```json
{
  "msisdn": "90000005",
  "iccid": "8910101000000000005",
  "imsi": "525010000005",
  "apn": "internet",
  "activation_code": "LPA:1$smdp.bss-cli.local$A4B29F81XK22M7PQ"
}
```

**Events consumed:**
- `order.in_progress` → decompose → reserve MSISDN + eSIM → create services → emit provisioning tasks
- `provisioning.task.completed` → advance relevant service; when all RFS activated + eSIM prepared → activate CFS → emit `service_order.completed`
- `provisioning.task.failed` (after max retries) → fail service order → emit `service_order.failed` → **cleanup**
- `provisioning.task.stuck` → mark service in stuck substate, wait for manual resolution

**Events published:**
- `service_order.created`, `service_order.in_progress`, `service_order.completed`, `service_order.failed`
- `service.designed`, `service.reserved`, `service.activated`, `service.terminated`

**Cleanup on failure — critical for eSIM honesty:**

If the service order fails after reservation, SOM calls `bss-clients.InventoryClient` to release both resources:

```python
await inventory_client.release_msisdn(msisdn)   # → quarantine (stubbed as 'available' in v0.1)
await inventory_client.release_esim(iccid)      # → back to 'available', no cooldown for unused
```

**Failure to release is the test that proves the architecture is honest.** Failure scenario 2 in the test plan is this exact case. Do not skip it.

### Service 3: `services/provisioning-sim/` (port **8010**)

**Endpoints:**
- `GET    /provisioning-api/v1/task/{id}`
- `GET    /provisioning-api/v1/task?serviceId={id}&state={state}`
- `POST   /provisioning-api/v1/task/{id}/resolve` — manual unstick, destructive
- `POST   /provisioning-api/v1/task/{id}/retry` — manual retry, destructive
- `GET    /provisioning-api/v1/fault-injection`
- `PATCH  /provisioning-api/v1/fault-injection/{id}` — enable/disable/adjust, admin-gated
- `GET /health`, `GET /ready`

**Core worker loop:**

```python
TASK_DURATIONS = {
    "HLR_PROVISION":        0.5,
    "PCRF_POLICY_PUSH":     0.3,
    "OCS_BALANCE_INIT":     0.2,
    "ESIM_PROFILE_PREPARE": 0.4,  # simulates SM-DP+ profile generation
    "HLR_DEPROVISION":      0.4,
}

async def process_task(task: ProvisioningTask):
    # 1. Check fault injection rules for task_type
    # 2. If "stuck" rule fires → state=stuck, do NOT complete, return
    # 3. If "fail_first_attempt" rule fires AND attempts==0 → fail, increment attempts, requeue
    # 4. If "slow" rule fires → sleep 2-5x normal duration
    # 5. Otherwise → sleep normal duration
    # 6. Mark completed, emit task.completed event
```

**ESIM_PROFILE_PREPARE simulation:**

Task simulates SM-DP+ preparing an eSIM profile. In a real system SM-DP+ generates the profile, signs it, stages it for LPA. In the sim:
- Sleep for 0.4s
- On completion, the eSIM profile is already in `reserved` state (transitioned by SOM at reservation time)
- The sim just validates that the profile exists and has an `activation_code`, then emits success
- On failure (fault injection), the eSIM remains in `reserved` with an error flag that SOM reads to decide retry vs fail

**Retry semantics:**
- On failure, increment attempts, re-queue if `attempts < max_attempts`
- After `max_attempts`, emit `task.failed` permanently
- Stuck tasks NEVER auto-retry — require manual `POST /task/{id}/resolve` or `/retry`

**Events consumed:** `provisioning.task.created`

**Events published:** `provisioning.task.started`, `task.completed`, `task.failed`, `task.stuck`, `task.resolved`

## The happy-path flow (end-to-end with eSIM)

```
POST /productOrder {customer_id: CUST-007, offering_id: PLAN_M}

COM:
  policy check (customer, COF, KYC, offering)
  → create order (acknowledged) → emit order.acknowledged
  → transition to in_progress → emit order.in_progress

SOM consumes order.in_progress:
  → lookup product-to-service mapping for PLAN_M
  → decompose → plan (1 CFS, 2 RFS, 2 resources, 5 tasks)
  → bss-clients.inventory.reserve_msisdn(preference) → 90000005
  → bss-clients.inventory.reserve_esim() → ICCID 8910101..., activation_code LPA:1$...
  → bss-clients.inventory.assign_msisdn_to_esim(iccid, msisdn)
  → create service_order (in_progress)
  → create CFS service (designed, characteristics populated with msisdn/iccid/activation_code)
  → create 2 RFS services (designed)
  → emit 5 provisioning.task.created events

provisioning-sim consumes task.created (5 parallel):
  → ESIM_PROFILE_PREPARE (0.4s) → emit task.completed
  → HLR_PROVISION for RFS_VOICE (0.5s) → emit task.completed
  → HLR_PROVISION for RFS_DATA (0.5s) → emit task.completed
  → PCRF_POLICY_PUSH (0.3s) → emit task.completed
  → OCS_BALANCE_INIT (0.2s) → emit task.completed

SOM consumes task.completed:
  → RFS_VOICE → activated
  → RFS_DATA → activated
  → all RFS activated + eSIM prepared → activate CFS → emit service.activated
  → CFS activated → service_order completed → emit service_order.completed

COM consumes service_order.completed:
  → read CFS characteristics (msisdn, iccid, activation_code)
  → transition order to completed → emit order.completed
  → call subscription.create(customer_id, offering_id, msisdn, iccid, payment_method_id)

Subscription (Phase 6 code consumes this call):
  → policy check → payment.charge → create subscription (pending)
  → bss-clients.inventory.assign_msisdn(msisdn, subscription.id)
  → bss-clients.inventory.assign_esim(iccid, subscription.id)
  → init bundle balance → transition to active
  → emit subscription.activated

Customer receives (via CLI in Phase 9, or scenario assertion in Phase 10):
  subscription.get_esim_activation(subscription_id)
  → returns { iccid, activation_code, qr_ascii }

Total wall-clock: ~1.9 seconds.
```

## Policies required this phase

**COM:**
- [ ] `order.create.customer_active_or_pending` — cross-service via CRMClient
- [ ] `order.create.requires_cof` — cross-service via PaymentClient
- [ ] `order.create.requires_verified_customer` — gated by `BSS_REQUIRE_KYC` env flag
- [ ] `order.create.offering_sellable` — cross-service via CatalogClient
- [ ] `order.cancel.forbidden_after_som_started`
- [ ] `order.transition.valid_from_state`

**SOM:**
- [ ] `service_order.create.requires_parent_order`
- [ ] `service_order.create.mapping_exists` — cross-service via CatalogClient
- [ ] `service.activate.requires_all_rfs_activated_and_esim_prepared`
- [ ] `service.terminate.releases_msisdn_and_recycles_esim`
- [ ] `service.transition.valid_from_state`

**Provisioning:**
- [ ] `provisioning_task.retry.max_attempts`
- [ ] `provisioning.resolve_stuck.requires_note`
- [ ] `provisioning.set_fault_injection.admin_only`

## Failure scenarios to test

All six are in the verification checklist. None are optional.

1. **HLR first-attempt fail → retry succeeds:** enable fault rule (`HLR_PROVISION / fail_first_attempt / p=1.0`), place order, observe retry, verify activation still completes, verify 1 task shows `attempts=2`.

2. **ESIM_PROFILE_PREPARE fail_always → resources released:** enable fault, place order, verify service_order → failed, verify MSISDN released back to `available`, verify eSIM back to `available` (NOT stuck in `reserved`). **This is the critical architecture-honesty test. Do not skip.**

3. **HLR stuck → manual resolve:** enable stuck rule, place order, verify service_order stays in_progress, `POST /task/{id}/resolve` moves it forward.

4. **All retries exhausted:** set `max_attempts=1`, enable `fail_always` on `OCS_BALANCE_INIT`, verify service_order → failed, product_order → failed, MSISDN and eSIM both released.

5. **Slow provisioning:** enable slow rule on PCRF, verify order still completes, trace shows longer duration.

6. **Concurrent orders:** 10 orders in parallel for different customers, all succeed, each gets unique MSISDN and unique eSIM, zero `SELECT FOR UPDATE` deadlocks.

## Test strategy

Phase 4/5 lessons apply: httpx tests for every endpoint with camelCase JSON, state machine parametrization, DB sequences, no in-memory counters.

New for Phase 7: **event-chain integration tests.** Because this is event-driven, some assertions can only be made after events settle. Use polling with a bounded timeout, not fixed sleeps.

```python
async def wait_for_order_state(order_id: str, target_state: str, timeout_s: float = 10):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        order = await com_client.get_order(order_id)
        if order.state == target_state:
            return order
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Order {order_id} did not reach {target_state} within {timeout_s}s")
```

### Required test files (per service)

**com/:**
- `test_order_api.py` — httpx tests for every endpoint, camelCase
- `test_order_state_machine.py` — parametrized transitions
- `test_order_policies.py` — all 6 policies with negative cases
- `test_order_cross_service_success.py` — real CRM, Payment, Catalog
- `test_order_cross_service_failures.py` — respx mocks for 404/422/503

**som/:**
- `test_decomposition.py` — pure function, matrix over offerings
- `test_som_state_machine.py` — parametrized
- `test_som_event_consumer.py` — event in → event out
- `test_resource_reservation.py` — real CRM inventory (happy) + respx (failures)
- `test_som_cleanup_on_failure.py` — **critical test for scenario 2**

**provisioning-sim/:**
- `test_worker_loop.py` — task processing with mocked duration
- `test_fault_injection.py` — each fault type, deterministic with p=1.0
- `test_retry_semantics.py` — fail → retry → succeed, max attempts exhausted
- `test_esim_profile_prepare.py` — task type specific

**Integration tests (at repo root `tests/integration/phase_07/`):**
- `test_happy_path_end_to_end.py` — the full flow from POST /productOrder to subscription.activated
- `test_failure_scenario_2_esim_release.py` — the critical honesty test
- `test_concurrent_orders_10.py` — parallel order creation with distinct resource allocation

## ID generation

Sequences: `order_mgmt.order_id_seq`, `order_mgmt.service_order_id_seq`, `service_inventory.service_id_seq`, `provisioning.task_id_seq`.

## Verification checklist

- [ ] `make up` brings up com, som, provisioning-sim alongside crm (hosts inventory), subscription, payment, catalog
- [ ] Happy-path order for PLAN_M completes end-to-end in <3 seconds wall-clock
- [ ] Resulting subscription has both `msisdn` and `iccid` populated
- [ ] `bsspsql -c "SELECT status FROM inventory.msisdn_pool WHERE msisdn = '90000005'"` → `assigned`
- [ ] `bsspsql -c "SELECT profile_state FROM inventory.esim_profile WHERE iccid = '...'"` → `reserved` (downloads happen post-activation, out of scope for sim)
- [ ] `service.get` on the CFS returns characteristics containing msisdn, iccid, activation_code
- [ ] `audit.domain_event ORDER BY occurred_at` shows the full ~17-event chain for one order
- [ ] Failure scenario 1 (HLR retry) → order completes, 1 task shows `attempts=2`
- [ ] **Failure scenario 2 (ESIM prep fail_always) → order fails, `inventory.msisdn_pool` shows MSISDN back to `available`, `inventory.esim_profile` shows eSIM back to `available` — critical test, do not skip**
- [ ] Failure scenario 3 (HLR stuck) → service_order stuck, `POST /task/{id}/resolve` unblocks
- [ ] Failure scenario 4 (OCS exhausted) → order fails, both resources released
- [ ] Failure scenario 5 (PCRF slow) → order completes, wall-clock longer than baseline
- [ ] Failure scenario 6 (10 concurrent) → all succeed, 10 distinct MSISDNs, 10 distinct ICCIDs, no conflicts
- [ ] Cancelling an order before SOM starts → allowed
- [ ] Cancelling an order after SOM started → 422 rule `order.cancel.forbidden_after_som_started`
- [ ] `BSS_REQUIRE_KYC=true` + unverified customer → `order.create` returns 422 rule `requires_verified_customer`
- [ ] `BSS_REQUIRE_KYC=true` + verified customer → order flows normally
- [ ] `grep -r "inventory\." services/som/ services/com/` returns **zero direct schema references** (must go via bss-clients)
- [ ] `make test` — catalog + crm + payment + subscription + com + som + provisioning-sim all green
- [ ] `docker compose build --no-cache com som provisioning-sim` builds clean
- [ ] Campaign OS schemas untouched

## Out of scope

- `bss` CLI integration (Phase 9)
- Real OTel trace rendering (Phase 11)
- Multi-CFS products (v0.2)
- Feasibility check logic (skip straight to `designed`)
- Real SM-DP+ protocol simulation (no actual ES9+ messages)
- MSISDN quarantine scheduler (v0.2, stub as 'available' for v0.1)
- Abandoned order cleanup job (v0.2)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md` (SOM + provisioning sections), `DATA_MODEL.md` (schemas `order_mgmt`, `service_inventory`, `provisioning`, `inventory`), `TOOL_SURFACE.md`, `DECISIONS.md`, `phases/PHASE_04.md` (inventory endpoints in CRM), `phases/PHASE_05.md` (bss-clients), `phases/PHASE_06.md` (subscription.create contract), `phases/PHASE_07.md`.
>
> This is the most ambitious phase. Budget 4-5 hours. If running over, tell me so we can split into 7a (provisioning-sim + SOM) and 7b (COM).
>
> Before writing any code, produce a plan that includes:
>
> 1. **COM order state machine table** — paste into DECISIONS.md under Phase 7 entry. Columns: From, Trigger, To, Guard, Action. Wait for approval before writing FSM code.
>
> 2. **SOM service state machine table** — same format, also in DECISIONS.md.
>
> 3. **Happy-path event sequence** — draw the full event chain with exact routing keys, payload schemas, and bss-clients HTTP calls. Highlight the 17 events that should appear in `audit.domain_event`.
>
> 4. **Decomposition plan for PLAN_M** — paste the exact `DecompositionPlan` dataclass that `decompose(order, mapping)` will return for PLAN_M. Confirm 1 CFS, 2 RFS, 2 resources, 5 provisioning tasks.
>
> 5. **Resource reservation path** — confirm SOM calls `bss-clients.InventoryClient.reserve_msisdn()` and `reserve_esim()`, NOT direct DB access. No `SELECT ... FROM inventory.*` anywhere in SOM's code.
>
> 6. **Cleanup on failure paths** — for each failure mode (service_order fails after reservation, task fails after max retries, service order cancelled mid-flow), paste the exact cleanup sequence. Every reserved resource must be released.
>
> 7. **Policy catalog** — all 14 policies with rule ID, module, cross-service dependency, negative-test case.
>
> 8. **Failure scenarios test plan** — for each of the 6 scenarios, paste the test skeleton including fault injection setup, assertion, cleanup. Scenario 2 (eSIM release on fail) is critical — highlight it.
>
> 9. **Test strategy** — confirm httpx tests for every endpoint with camelCase, parametrized state machines, event-chain integration tests with polling (not fixed sleeps), sequence-based IDs.
>
> 10. **Provisioning sim worker loop** — paste the `process_task` function showing fault injection hooks, retry counter, duration simulation. Confirm `ESIM_PROFILE_PREPARE` is a first-class task type.
>
> Wait for my approval before writing any code.
>
> After I approve, implement in this order:
> 1. `provisioning-sim` first (simplest, unblocks others)
> 2. `som` with decomposition + state machine + event handling + inventory reservation via bss-clients
> 3. `com` with order FSM + inter-service calls + cleanup paths
> 4. Wire all three into `docker-compose.yml`
> 5. Integration tests: happy path first, then all 6 failure scenarios (scenario 2 before any others)
> 6. Run full verification checklist
>
> Do not commit.

## The trap

**This phase has the most moving parts.** Force sequential build: sim first, verify in isolation, then SOM, then COM. Do not parallelize.

**Use the audit table as your debugger.** Query `audit.domain_event ORDER BY occurred_at DESC LIMIT 50` whenever something doesn't work — the event sequence tells you where the chain broke.

**Don't let Claude Code bypass bss-clients for inventory access.** SOM calls CRM's inventory endpoints via HTTP. The temptation to "just query the shared Postgres directly" must be resisted. Grep check after implementation: `grep -r "inventory\." services/som/ services/com/` returns zero direct schema references.

**Do not skip failure scenario 2.** eSIM release on failure is the test that proves the architecture is honest. If the eSIM stays stuck in `reserved` after a failed order, inventory leaks until manual admin intervention — a real operational bug disguised as a happy-path success. Every test run must exercise this scenario.

**If Claude Code proposes "retry all failed tasks automatically," reject it.** Stuck tasks require manual resolution by design. Auto-retry on stuck is how you lose operator oversight of real outages.

**Budget discipline.** If you hit the 4-hour mark and COM hasn't started, stop, commit 7a as is (provisioning-sim + SOM, with a test-only COM stub), tag it, and start Phase 7b in a fresh session. Two clean phases are worth more than one muddled one.
