# Phase 4 — CRM Service (full lightweight CRM + KYC + Inventory)

> **Second-most-important phase.** Write Policy doctrine becomes real code, Inventory domain embedded here (v0.1), KYC attestation handled.

## Goal

A functional lightweight CRM service covering Customer, Contact Medium, Interaction, Case, Ticket, **KYC attestation intake**, and **Inventory (MSISDN + eSIM profile pools)** — all with proper state machines, SLA tracking, and a complete Write Policy layer.

By the end of this phase, you can: create a customer, submit a KYC attestation, open a case, spawn tickets, assign/resolve, close the case, and read MSISDN/eSIM availability from the inventory sub-domain. The CRM service becomes the customer-facing + identity + inventory service.

## Deliverables

### Service: `services/crm/` (port **8002**)

Follows the Phase 3 pattern exactly, plus introduces the `policies/` and `services/` layers for the first time, plus hosts the Inventory domain.

```
services/crm/app/
├── main.py, config.py, logging.py, middleware.py, dependencies.py, auth_context.py, lifespan.py
├── api/
│   ├── tmf/
│   │   ├── customer.py          # TMF629
│   │   ├── contact.py           # TMF629 contact medium
│   │   ├── interaction.py       # TMF683
│   │   └── ticket.py            # TMF621
│   ├── crm/                     # custom
│   │   ├── case.py
│   │   ├── kyc.py               # attestation intake
│   │   └── agent.py             # read-only
│   └── inventory/               # Inventory sub-domain
│       ├── msisdn.py
│       └── esim.py
├── schemas/
│   ├── tmf/                     # TMF-shaped (camelCase)
│   └── internal/                # DTOs (snake_case)
├── repositories/
│   ├── customer_repo.py
│   ├── case_repo.py
│   ├── ticket_repo.py
│   ├── interaction_repo.py
│   ├── kyc_repo.py
│   ├── msisdn_repo.py           # inventory
│   └── esim_repo.py             # inventory
├── policies/
│   ├── base.py                  # PolicyViolation, @policy decorator
│   ├── customer.py
│   ├── kyc.py
│   ├── case.py
│   ├── ticket.py
│   ├── inventory.py             # msisdn + esim reservation policies
│   └── catalog.py               # central rule_id → callable registry
├── services/
│   ├── customer_service.py
│   ├── kyc_service.py
│   ├── case_service.py
│   ├── ticket_service.py
│   └── inventory_service.py
├── domain/
│   ├── case_state.py
│   └── ticket_state.py
└── events/
    ├── publisher.py             # uses bss-events
    └── handlers.py              # (none this phase)
```

## Endpoints

### TMF629 Customer
- `POST   /tmf-api/customerManagement/v4/customer`
- `GET    /tmf-api/customerManagement/v4/customer`
- `GET    /tmf-api/customerManagement/v4/customer/{id}`
- `PATCH  /tmf-api/customerManagement/v4/customer/{id}` — policy-gated
- `POST   /tmf-api/customerManagement/v4/customer/{id}/contactMedium`
- `DELETE /tmf-api/customerManagement/v4/customer/{id}/contactMedium/{cmId}` — destructive

### KYC (custom — channel-layer intake)
- `POST /crm-api/v1/customer/{id}/kyc-attestation` — channel submits signed attestation
- `GET  /crm-api/v1/customer/{id}/kyc-status`

### TMF683 Interaction
- `POST /tmf-api/customerInteractionManagement/v1/interaction`
- `GET  /tmf-api/customerInteractionManagement/v1/interaction?customerId={id}&since={ts}`

### Custom Case
- `POST  /crm-api/v1/case`
- `GET   /crm-api/v1/case/{id}`
- `GET   /crm-api/v1/case?customerId=&state=&assignedAgentId=`
- `POST  /crm-api/v1/case/{id}/note`
- `PATCH /crm-api/v1/case/{id}`
- `POST  /crm-api/v1/case/{id}/close`

### TMF621 Ticket
- `POST   /tmf-api/troubleTicket/v4/troubleTicket`
- `GET    /tmf-api/troubleTicket/v4/troubleTicket/{id}`
- `GET    /tmf-api/troubleTicket/v4/troubleTicket`
- `PATCH  /tmf-api/troubleTicket/v4/troubleTicket/{id}`
- `POST   /tmf-api/troubleTicket/v4/troubleTicket/{id}/resolve`
- `POST   /tmf-api/troubleTicket/v4/troubleTicket/{id}/cancel` — destructive

### Inventory (new in v3)
- `GET  /inventory-api/v1/msisdn?status=available&prefix=9000` — list with filters
- `GET  /inventory-api/v1/msisdn/{msisdn}`
- `POST /inventory-api/v1/msisdn/{msisdn}/reserve` — internal, called by SOM via bss-clients
- `POST /inventory-api/v1/msisdn/{msisdn}/assign` — internal, idempotent
- `POST /inventory-api/v1/msisdn/{msisdn}/release` — internal
- `GET  /inventory-api/v1/esim?status=available` — list
- `GET  /inventory-api/v1/esim/{iccid}`
- `POST /inventory-api/v1/esim/reserve` — internal, reserves next available profile
- `POST /inventory-api/v1/esim/{iccid}/assign-msisdn` — bind eSIM to MSISDN
- `POST /inventory-api/v1/esim/{iccid}/mark-downloaded` — lifecycle transition
- `POST /inventory-api/v1/esim/{iccid}/mark-activated` — lifecycle transition
- `POST /inventory-api/v1/esim/{iccid}/recycle` — on termination
- `GET  /inventory-api/v1/esim/{iccid}/activation` — returns LPA activation code + QR payload

### Agent (read-only)
- `GET /crm-api/v1/agent`
- `GET /crm-api/v1/agent/{id}`

Health/ready per Phase 3.

## State machines

### Case
```
States: open, in_progress, pending_customer, resolved, closed

open              --take-->            in_progress         [action: log_interaction]
in_progress       --await_customer-->  pending_customer
pending_customer  --resume-->          in_progress
in_progress       --resolve-->         resolved            [guard: all_tickets_resolved]
resolved          --close-->           closed              [guard: resolution_code_set]
open              --resolve-->         resolved            [guard: no_tickets OR all_resolved]
any except closed --cancel-->          closed              [action: cancel_open_tickets]
```

### Ticket
```
States: open, acknowledged, in_progress, pending, resolved, closed, cancelled

open             --ack-->       acknowledged        [guard: assigned_agent]
acknowledged     --start-->     in_progress
in_progress      --wait-->      pending
pending          --resume-->    in_progress
in_progress      --resolve-->   resolved            [guard: resolution_notes]
resolved         --close-->     closed
resolved         --reopen-->    in_progress
any non-terminal --cancel-->    cancelled
```

### eSIM profile lifecycle
```
States: available, reserved, downloaded, activated, suspended, recycled

available  --reserve-->       reserved        [atomic SELECT FOR UPDATE SKIP LOCKED]
reserved   --assign_msisdn--> reserved        [sets assigned_msisdn, stays reserved until download]
reserved   --download-->      downloaded      [customer scans QR, SM-DP+ delivers profile]
downloaded --activate-->      activated       [first attach on HLR]
activated  --suspend-->       suspended       [subscription blocked]
suspended  --activate-->      activated
activated  --recycle-->       recycled        [subscription terminated, 90-day cooldown then available]
reserved   --release-->       available       [cancelled order path]
```

**Fill all three tables in DECISIONS.md before coding.**

## Write Policy implementation

### Base layer (`app/policies/base.py`)

```python
class PolicyViolation(Exception):
    def __init__(self, rule: str, message: str, context: dict | None = None):
        self.rule = rule
        self.message = message
        self.context = context or {}

def policy(rule_id: str):
    def wrap(fn):
        fn.__policy_rule__ = rule_id
        return fn
    return wrap
```

### Example policy: KYC

```python
# app/policies/kyc.py
from app.auth_context import current

@policy("customer.attest_kyc.customer_exists")
async def check_customer_exists(customer_id: str, repo):
    if not await repo.get(customer_id):
        raise PolicyViolation(
            rule="customer.attest_kyc.customer_exists",
            message=f"Customer {customer_id} does not exist",
            context={"customer_id": customer_id}
        )

@policy("customer.attest_kyc.document_hash_unique_per_tenant")
async def check_document_unique(doc_type: str, doc_hash: str, kyc_repo):
    ctx = current()
    existing = await kyc_repo.find_by_document_hash(
        tenant_id=ctx.tenant,
        document_type=doc_type,
        document_number_hash=doc_hash
    )
    if existing:
        raise PolicyViolation(
            rule="customer.attest_kyc.document_hash_unique_per_tenant",
            message="This identity document is already registered",
            context={"document_type": doc_type}  # never leak the hash
        )

@policy("customer.attest_kyc.attestation_signature_valid")
async def check_attestation_signature(attestation: dict):
    # v0.1 stub: accept any payload with a `signature` field
    # Phase 12: real JWS validation against channel provider public keys
    if "signature" not in attestation:
        raise PolicyViolation(
            rule="customer.attest_kyc.attestation_signature_valid",
            message="Attestation payload missing signature",
            context={}
        )
```

### Error response shape (TMF-aligned)

On `PolicyViolation`, middleware returns HTTP 422:
```json
{
  "code": "POLICY_VIOLATION",
  "reason": "case.close.requires_all_tickets_resolved",
  "message": "Case CASE-042 has 2 open tickets (TKT-101, TKT-103)",
  "referenceError": "https://docs.bss-cli.dev/policies/case.close.requires_all_tickets_resolved",
  "context": { "case_id": "CASE-042", "open_tickets": ["TKT-101", "TKT-103"] }
}
```

## KYC attestation intake flow

The channel layer (mobile app, web portal) has already run an eKYC vendor flow (Myinfo, Jumio, Onfido) and obtained a signed attestation. It submits it to BSS-CLI via:

```http
POST /crm-api/v1/customer/CUST-007/kyc-attestation
Content-Type: application/json
X-BSS-Channel: mobile-app
X-BSS-Actor: channel:singpass-mobile

{
  "provider": "myinfo",
  "provider_reference": "myinfo-tx-9f82a1",
  "document_type": "nric",
  "document_number": "S1234567A",       ← hashed server-side, never stored
  "document_country": "SG",
  "date_of_birth": "1985-03-15",
  "nationality": "SG",
  "verified_at": "2026-04-11T09:15:00+08:00",
  "attestation_payload": {
    "issuer": "singpass.gov.sg",
    "subject_id": "...",
    "claims": { "name": "Ck Tan", ... },
    "signature": "eyJhbGc..."            ← v0.1 stub check; Phase 12 real JWS
  }
}
```

Service logic:
1. Validate via policies (`customer_exists`, `signature_valid`, `document_unique`)
2. Compute `document_number_hash = sha256(document_number)`
3. **Discard plaintext document number immediately** — never written to DB or logs
4. Insert into `crm.customer_identity`
5. Update `crm.customer` — set `kyc_status='verified'`, `kyc_verified_at=now`, `kyc_verification_method=provider`, `kyc_reference=provider_reference`
6. Emit `customer.kyc_attested` event
7. Auto-log interaction with `channel=<from header>`, `summary="KYC attested via {provider}"`
8. Return customer with updated `kyc_status`

### structlog redaction

Add a redaction processor that strips any field named `document_number`, `cvv`, `card_number`, `ki`, `pan`, `password`, `token` (except when the key ends with `_ref` or `_id`). Test with a log emission that includes `document_number` and verify it's `***REDACTED***` in output.

## Inventory domain logic

### MSISDN reservation (called by SOM)

```python
async def reserve_msisdn(preference: str | None, tenant_id: str) -> str:
    async with db.begin():
        if preference:
            row = await db.execute(
                text("""
                    SELECT msisdn FROM inventory.msisdn_pool
                    WHERE msisdn = :m AND status = 'available' AND tenant_id = :t
                    FOR UPDATE SKIP LOCKED
                """), {"m": preference, "t": tenant_id}
            )
        else:
            row = await db.execute(
                text("""
                    SELECT msisdn FROM inventory.msisdn_pool
                    WHERE status = 'available' AND tenant_id = :t
                    ORDER BY msisdn LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """), {"t": tenant_id}
            )
        msisdn = row.scalar_one_or_none()
        if not msisdn:
            raise PolicyViolation(
                rule="msisdn.reserve.no_available",
                message="No MSISDN available matching criteria",
                context={"preference": preference}
            )
        await db.execute(
            text("UPDATE inventory.msisdn_pool SET status='reserved', reserved_at=NOW() WHERE msisdn=:m"),
            {"m": msisdn}
        )
        return msisdn
```

Same pattern for eSIM reservation (`FOR UPDATE SKIP LOCKED` on `esim_profile` where `profile_state='available'`).

### eSIM activation code generation

The activation code and matching_id are generated at **seed time** (Phase 2), not on reservation. This means each eSIM profile has a pre-generated `LPA:1$smdp.bss-cli.local$<matching_id>` string that sits unused until reservation. This matches real SM-DP+ behavior where profiles are pre-provisioned.

At reservation time, the profile just transitions `available → reserved` and the activation code is revealed to the customer via `subscription.get_esim_activation`.

## Interaction auto-logging

Every write operation on a customer-owning aggregate (case, ticket, contact change, KYC attestation) automatically creates an `interaction` row via a decorator on the service method. The interaction's `channel` comes from `auth_context.current().channel` (set by middleware from `X-BSS-Channel` header).

This is how we get "every touchpoint logged" without asking callers to remember.

## Policies required this phase

### Customer
- [ ] `customer.create.email_unique`
- [ ] `customer.create.requires_contact_medium`
- [ ] `customer.close.no_active_subscriptions` — stub returning true; real check wired Phase 6

### KYC
- [ ] `customer.attest_kyc.customer_exists`
- [ ] `customer.attest_kyc.attestation_signature_valid` — v0.1 stub
- [ ] `customer.attest_kyc.document_hash_unique_per_tenant`

### Case
- [ ] `case.open.customer_must_be_active`
- [ ] `case.transition.valid_from_state`
- [ ] `case.close.requires_all_tickets_resolved`
- [ ] `case.close.requires_resolution_code`
- [ ] `case.add_note.case_not_closed`

### Ticket
- [ ] `ticket.open.requires_customer_or_case`
- [ ] `ticket.assign.agent_must_be_active`
- [ ] `ticket.transition.valid_from_state`
- [ ] `ticket.resolve.requires_resolution_notes`
- [ ] `ticket.cancel.not_if_resolved_or_closed`

### Inventory
- [ ] `msisdn.reserve.status_must_be_available`
- [ ] `msisdn.release.only_if_reserved_or_assigned`
- [ ] `esim.reserve.status_must_be_available`
- [ ] `esim.release.only_if_reserved_or_assigned`
- [ ] `esim.assign_msisdn.msisdn_must_be_reserved`

Every policy needs a negative-path test (violation → 422) and a positive-path test.

## Verification checklist

- [ ] `make up` (services + external infra, or `make up-all`) brings up crm healthy
- [ ] `POST /customer` with fresh email → creates customer, party, individual, contact medium in one transaction
- [ ] Customer starts with `kyc_status='not_verified'`
- [ ] `POST /kyc-attestation` → `kyc_status='verified'`, `customer_identity` row inserted
- [ ] `customer_identity.document_number_hash` is SHA-256 hex, NOT plaintext
- [ ] `docker compose logs crm | grep S1234567A` returns **zero hits** (plaintext never logged)
- [ ] Duplicate document attestation (same doc_hash) → 422 `document_hash_unique_per_tenant`
- [ ] `POST /customer` with duplicate email → 422 `customer.create.email_unique`
- [ ] `POST /case` + `POST /ticket` with `caseId` link correctly
- [ ] `POST /case/{id}/close` with open tickets → 422 with open ticket IDs in context
- [ ] Resolve all tickets, close case → succeeds, events in RabbitMQ and `audit.domain_event`
- [ ] `ticket.assign` to terminated agent → 422
- [ ] Invalid state transition → 422
- [ ] Every write creates an `audit.domain_event` row in the same transaction
- [ ] Every write auto-creates an `interaction` row with correct channel
- [ ] `POST /inventory-api/v1/msisdn/90000005/reserve` → status='reserved', concurrent reserves (10 parallel on same MSISDN) return 1 success + 9 failures
- [ ] `POST /inventory-api/v1/esim/reserve` → returns an available profile, transitions to reserved, concurrent reserves don't double-allocate
- [ ] `GET /inventory-api/v1/esim/{iccid}/activation` → returns `LPA:1$smdp.bss-cli.local$<matching_id>`
- [ ] `make crm-test` passes (unit tests for state machines, policy tests, API tests)
- [ ] No business logic in `api/` files (manual review)
- [ ] No direct repository calls from `api/` files (manual review)
- [ ] All write services read `auth_context.current()` instead of hardcoded values

## Out of scope

- CRM dashboards / ASCII renderers (Phase 9)
- Organization party type (v0.1: individual only)
- Attachments on tickets (v0.2)
- Multi-channel inbound beyond header-driven channel (v0.2)
- Email/SMS sending (v0.2)
- Continuous SLA monitoring (computed at resolve, not monitored)
- Real JWS validation for KYC attestations (Phase 12)
- MSISDN quarantine scheduler (post-v0.1)

## Session prompt

> Read `CLAUDE.md`, `DATA_MODEL.md` (especially `crm` and `inventory` schemas), `phases/PHASE_03.md` (for the service pattern), `phases/PHASE_04.md`.
>
> Before writing any code:
> 1. Fill in the Case, Ticket, and eSIM state machine tables in `DECISIONS.md`
> 2. List every policy you will implement with its module location
> 3. List every endpoint and which service method it calls
> 4. Confirm the Inventory sub-domain lives inside this service (not a separate container)
> 5. Confirm `X-BSS-Actor` / `X-BSS-Channel` headers flow through `auth_context.set_for_request()` in middleware
> 6. Confirm KYC plaintext is hashed and discarded immediately, structlog redaction is wired
>
> Wait for approval. Implement in this order: domain state machines → policies → services → repositories → routers → tests. Bottom-up.

## The discipline

**Policies are the product.** Be paranoid. When in doubt, add the policy.

**No direct repo calls from routers. No policy bypass in services.** Two layers of enforcement, both enforced by code review.

**Never log plaintext NRIC / document numbers / Ki values.** The redaction test is non-negotiable — it must actually run and actually pass.

**Inventory is a sub-domain, not a sub-service.** Own schema, own repositories, own policies — but same FastAPI process. Extraction to a separate container is a v0.2 refactor that should be mechanical because the boundaries are clean.
