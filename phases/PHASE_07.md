# Phase 7 — COM + SOM + Provisioning Simulator (with eSIM)

> **The most ambitious phase.** Three services, two state machines, one simulator, eSIM integration, and an event-driven decomposition flow. Budget 4-5 hours. If running over, split into 7a (prov-sim + SOM) and 7b (COM).

## Goal

Three new services implementing the full order-to-activation flow, including eSIM profile reservation and activation code delivery.

1. **COM** (TMF622) — customer-facing order
2. **SOM** (TMF641 + TMF638) — decomposes commercial order into service orders, tracks CFS/RFS/Resource lifecycle, reserves MSISDN + eSIM
3. **Provisioning Simulator** — stands in for HLR/PCRF/OCS/SM-DP+, configurable fault injection

By end of phase: placing a commercial order triggers SOM, which reserves an MSISDN + eSIM profile and emits provisioning tasks. The simulator completes tasks (including `ESIM_PROFILE_PREPARE`). Flow returns through SOM → COM → Subscription. End-to-end activation works, customer receives an LPA activation code.

## Deliverables

### Service 1: `services/com/` (port **8004**)

Follows Phase 3/4/5/6 pattern. Stateful with order FSM.

**Endpoints (TMF622):**
- `POST   /tmf-api/productOrderingManagement/v4/productOrder`
- `GET    /tmf-api/productOrderingManagement/v4/productOrder`
- `GET    /tmf-api/productOrderingManagement/v4/productOrder/{id}`
- `PATCH  /tmf-api/productOrderingManagement/v4/productOrder/{id}`
- `POST   /tmf-api/productOrderingManagement/v4/productOrder/{id}/cancel` — destructive
- Health/ready

**State machine:**
```
acknowledged → in_progress → completed
                           ↘ failed
            → cancelled (only from acknowledged or early in_progress)
```

**Flow:**
1. `POST /productOrder` → policies (customer exists, has COF, has KYC if enforced, offering sellable) → create order in `acknowledged` → emit `order.acknowledged`
2. Transition to `in_progress` → emit `order.in_progress`
3. Consume `service_order.completed` → transition to `completed` → call `subscription-api` to create subscription (passing msisdn + iccid from the service order's characteristics)
4. Consume `service_order.failed` → transition to `failed` → emit `order.failed` → trigger cleanup (release MSISDN + eSIM via inventory-api)

### Service 2: `services/som/` (port **8005**)

**Endpoints (TMF641 + TMF638 read):**
- `POST   /tmf-api/serviceOrderingManagement/v4/serviceOrder` — internal
- `GET    /tmf-api/serviceOrderingManagement/v4/serviceOrder/{id}`
- `GET    /tmf-api/serviceOrderingManagement/v4/serviceOrder?commercialOrderId={id}`
- `GET    /tmf-api/serviceInventoryManagement/v4/service/{id}`
- `GET    /tmf-api/serviceInventoryManagement/v4/service?subscriptionId={id}`
- Health/ready

**Decomposition logic** (`app/domain/decomposition.py`):
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
            TaskCreation(type="ESIM_PROFILE_PREPARE", target="CFS"),   # prepare SM-DP+ download
            TaskCreation(type="HLR_PROVISION",       target="RFS_VOICE"),
            TaskCreation(type="HLR_PROVISION",       target="RFS_DATA"),
            TaskCreation(type="PCRF_POLICY_PUSH",    target="RFS_DATA"),
            TaskCreation(type="OCS_BALANCE_INIT",    target="CFS"),
        ]
    )
```

**Resource reservation via bss-clients (calls CRM inventory sub-domain):**
```python
async def reserve_resources(order, plan):
    async with inventory_client() as inv:
        msisdn = await inv.reserve_msisdn(preference=order.msisdn_preference)
        esim = await inv.reserve_esim()
        await inv.assign_msisdn_to_esim(iccid=esim.iccid, msisdn=msisdn)
    return {"msisdn": msisdn, "iccid": esim.iccid, "activation_code": esim.activation_code}
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

**Service state machine:**
```
feasibility_checked → designed → reserved → activated → terminated
                                         ↘ failed
```

RFS transitions via provisioning task events. CFS can only transition to `activated` once **all** its RFS are activated AND `ESIM_PROFILE_PREPARE` has completed (enforced by policy `service.activate.requires_all_rfs_activated_and_esim_prepared`).

**Events consumed:**
- `order.in_progress` → decompose → reserve MSISDN + eSIM → create services → emit provisioning tasks
- `provisioning.task.completed` → advance relevant service; if all RFS activated + eSIM prepared → activate CFS → emit `service_order.completed`
- `provisioning.task.failed` (after max retries) → fail service order → emit `service_order.failed` → cleanup
- `provisioning.task.stuck` → mark service in stuck substate, wait for manual resolution

**Events published:**
- `service_order.created`, `service_order.in_progress`, `service_order.completed`, `service_order.failed`
- `service.designed`, `service.reserved`, `service.activated`, `service.terminated`

**Cleanup on failure:**
If the service order fails after reservation, SOM releases the MSISDN (back to available after 90-day quarantine — stub the quarantine in v0.1, just mark available) and the eSIM profile (back to available — no cooldown for unused profiles).

### Service 3: `services/provisioning-sim/` (port **8010**)

**Endpoints:**
- `GET    /provisioning-api/v1/task/{id}`
- `GET    /provisioning-api/v1/task?serviceId={id}&state={state}`
- `POST   /provisioning-api/v1/task/{id}/resolve` — manual unstick
- `POST   /provisioning-api/v1/task/{id}/retry` — manual retry
- `GET    /provisioning-api/v1/fault-injection`
- `PATCH  /provisioning-api/v1/fault-injection/{id}` — enable/disable/adjust
- Health/ready

**Core worker loop:**
```python
TASK_DURATIONS = {
    "HLR_PROVISION":        0.5,
    "PCRF_POLICY_PUSH":     0.3,
    "OCS_BALANCE_INIT":     0.2,
    "ESIM_PROFILE_PREPARE": 0.4,   # simulates SM-DP+ profile generation
    "HLR_DEPROVISION":      0.4,
}

async def process_task(task: ProvisioningTask):
    # 1. Check fault injection rules for task_type
    # 2. If "stuck" rule fires → state=stuck, do NOT complete, return
    # 3. If "fail_first_attempt" rule fires AND attempts==0 → fail, increment attempts
    # 4. If "slow" rule fires → sleep 2-5x normal duration
    # 5. Otherwise → sleep normal duration
    # 6. Mark completed, emit task.completed event
```

**ESIM_PROFILE_PREPARE simulation:**

The task simulates the SM-DP+ preparing an eSIM profile for download. In a real system, SM-DP+ generates the profile, signs it, and stages it for the LPA. In the sim:
- Sleep for 0.4s
- On completion, the eSIM profile is already in `reserved` state (transitioned by SOM at reservation time)
- The sim just validates that the profile exists and has an activation_code, then emits success
- On failure (fault injection), the eSIM remains in `reserved` with an error flag that SOM reads to decide retry

**Retry semantics:**
- On failure, increment attempts, re-queue if `attempts < max_attempts`
- After max_attempts, emit `task.failed` permanently
- Stuck tasks NEVER auto-retry — require manual `POST /task/{id}/resolve` or `/retry`

**Events consumed:** `provisioning.task.created`

**Events published:** `provisioning.task.started`, `task.completed`, `task.failed`, `task.stuck`, `task.resolved`

## The happy-path flow (end-to-end with eSIM)

```
POST /productOrder {customer_id, offering_id: PLAN_M}

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

provisioning-sim consumes task.created:
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

Subscription:
  → policy check → payment.charge → create subscription (pending)
  → bss-clients.inventory.assign_msisdn(msisdn, subscription.id)
  → bss-clients.inventory.assign_esim(iccid, subscription.id)
  → init bundle balance → transition to active
  → emit subscription.activated

Customer receives (via CLI or scenario assertion):
  subscription.get_esim_activation(subscription_id)
  → returns { iccid, activation_code, qr_ascii }

Total wall-clock: ~1.9 seconds.
```

## Policies required this phase

**COM:**
- [ ] `order.create.customer_active_or_pending`
- [ ] `order.create.requires_cof`
- [ ] `order.create.requires_verified_customer` (gated by `BSS_REQUIRE_KYC` env flag)
- [ ] `order.create.offering_sellable`
- [ ] `order.cancel.forbidden_after_som_started`
- [ ] `order.transition.valid_from_state`

**SOM:**
- [ ] `service_order.create.requires_parent_order`
- [ ] `service_order.create.mapping_exists`
- [ ] `service.activate.requires_all_rfs_activated_and_esim_prepared`
- [ ] `service.terminate.releases_msisdn_and_recycles_esim`
- [ ] `service.transition.valid_from_state`

**Provisioning:**
- [ ] `provisioning_task.retry.max_attempts`
- [ ] `provisioning.resolve_stuck.requires_note`
- [ ] `provisioning.set_fault_injection.admin_only`

## Failure scenarios to test

1. **HLR first-attempt fail → retry succeeds:** enable fault rule, place order, observe retry, verify activation still completes
2. **ESIM_PROFILE_PREPARE fail_always:** enable fault, place order, verify SOM failure, verify MSISDN and eSIM released back to `available` (not stuck in `reserved`)
3. **HLR stuck:** enable stuck rule, place order, verify service_order stays in_progress, `POST /task/{id}/resolve` moves it forward
4. **All retries exhausted:** set max_attempts=1, enable fail_always on OCS_BALANCE_INIT, verify service_order → failed, product_order → failed, MSISDN and eSIM both released
5. **Slow provisioning:** enable slow rule on PCRF, verify order still completes, trace shows longer duration
6. **Concurrent orders:** 10 orders in parallel for different customers, all succeed, each gets unique MSISDN and unique eSIM

## Verification checklist

- [ ] `make up` brings up com, som, provisioning-sim alongside crm (hosts inventory) and previous services
- [ ] Happy-path order for PLAN_M completes end-to-end in <3 seconds wall-clock
- [ ] Resulting subscription has both `msisdn` and `iccid` populated
- [ ] `inventory.msisdn_pool` shows the MSISDN in `assigned` state
- [ ] `inventory.esim_profile` shows the profile in `reserved` state (downloads happen post-activation, out of scope for sim)
- [ ] `service.get` on the CFS returns characteristics containing msisdn, iccid, activation_code
- [ ] `audit.domain_event` ordered by occurred_at shows the full ~17-event chain
- [ ] Failure scenario 1 (HLR retry) → order still completes, 1 task shows attempts=2
- [ ] Failure scenario 2 (ESIM prep fail_always) → order fails, MSISDN released, eSIM released — critical test, do not skip
- [ ] Failure scenario 3 (HLR stuck) → order stuck, resolve endpoint unblocks
- [ ] Failure scenario 4 (OCS exhausted) → order fails, both resources released
- [ ] Failure scenario 5 (PCRF slow) → order completes, longer wall-clock
- [ ] Failure scenario 6 (10 concurrent) → all succeed, 10 distinct MSISDNs, 10 distinct ICCIDs, no conflicts
- [ ] Cancelling an order before SOM starts → allowed
- [ ] Cancelling an order after SOM started → 422 `order.cancel.forbidden_after_som_started`
- [ ] `BSS_REQUIRE_KYC=true` + unverified customer → `order.create` returns 422 with rule `requires_verified_customer`
- [ ] `BSS_REQUIRE_KYC=true` + verified customer → order flows normally
- [ ] `make com-test`, `make som-test`, `make provisioning-sim-test` all pass

## Out of scope

- `bss` CLI integration (Phase 9)
- True OTel trace rendering (Phase 11)
- Multi-CFS products (v0.2)
- Feasibility check logic (skip straight to `designed`)
- Real SM-DP+ protocol simulation (no actual ES9+ messages)
- MSISDN quarantine scheduler (v0.2)
- Abandoned order cleanup job (v0.2)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md` (SOM + provisioning sections), `DATA_MODEL.md` (schemas `order_mgmt`, `service_inventory`, `provisioning`, `inventory`), `phases/PHASE_04.md` (inventory endpoints in CRM), `phases/PHASE_06.md`, `phases/PHASE_07.md`.
>
> Before writing any code:
> 1. Fill in the COM order state machine table in `DECISIONS.md`
> 2. Fill in the SOM service state machine table in `DECISIONS.md`
> 3. Draw the happy-path event sequence with exact routing keys, payload schemas, and bss-clients HTTP calls
> 4. List every policy per service with test cases
> 5. Confirm SOM reserves MSISDN + eSIM via bss-clients to CRM's inventory endpoints, NOT direct DB access
> 6. Confirm failure scenario 2 (eSIM release on failure) is in the test plan — this is the critical new test in v3
>
> Wait for approval. Implement in this order:
> 1. `provisioning-sim` first (simplest, unblocks others) — include ESIM_PROFILE_PREPARE task type
> 2. `som` with decomposition + state machine + event handling + inventory reservation via bss-clients
> 3. `com` with order FSM + inter-service calls
> 4. Wire all three into docker-compose
> 5. End-to-end tests: happy path + all 6 failure scenarios
>
> After implementation, run full verification. Do not commit.

## The discipline

**This phase has the most moving parts of any phase.** Force sequential build: sim first, verify in isolation, then SOM, then COM. Do not parallelize.

**Use the audit table as your debugger.** Query `audit.domain_event ORDER BY occurred_at DESC LIMIT 50` whenever something doesn't work — the event sequence tells you where the chain broke.

**Don't let Claude Code bypass bss-clients for inventory access.** SOM calls CRM's inventory endpoints via HTTP. Temptation to "just query the shared Postgres directly" must be resisted — the whole point of the schema boundary is that it's enforced socially now and mechanically later. Grep check after implementation: `grep -r "inventory\." services/som/` should return zero direct schema references.

**Don't skip failure scenario 2.** eSIM release on failure is the test that proves the architecture is honest. If the eSIM stays stuck in `reserved` after a failed order, inventory leaks until manual admin intervention — a real operational bug disguised as a happy-path success.

**If this phase takes more than 5 hours, split into 7a (provisioning-sim + SOM) and 7b (COM).** Better two clean phases than one muddled one.
