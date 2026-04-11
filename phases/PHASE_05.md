# Phase 5 — Payment Service

## Goal

The Payment service. Mock tokenizer, card-on-file storage, charge attempts, plus the first version of `bss-clients` — the shared HTTP client package every later service uses for cross-service calls. Short phase — most of the pattern work was done in Phase 4. This is a clean clone of the Phase 3/4 pattern applied to a simpler domain, plus one new shared package.

## Deliverables

### 1. Service: `services/payment/` (port **8003**)

Clone the Phase 4 CRM layout: `api/`, `schemas/`, `repositories/`, `policies/`, `services/`, `events/`, `domain/`, `auth_context.py`, `config.py` using the `_REPO_ROOT` pattern from the Phase 3 chore fix.

### 2. Endpoints (TMF676)

- `POST   /tmf-api/paymentMethodManagement/v4/paymentMethod` — register a **pre-tokenized** payment method
- `GET    /tmf-api/paymentMethodManagement/v4/paymentMethod?customerId={id}`
- `GET    /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}`
- `DELETE /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}` — destructive
- `POST   /tmf-api/paymentManagement/v4/payment` — charge an existing payment method
- `GET    /tmf-api/paymentManagement/v4/payment/{id}`
- `GET    /tmf-api/paymentManagement/v4/payment?customerId={id}`
- `GET /health`, `GET /ready`

### 3. The public API takes tokens, NOT cards

**Non-negotiable.** The public `POST /paymentMethod` endpoint takes a pre-tokenized request:

```json
{
  "customerId": "CUST-007",
  "type": "card",
  "tokenizationProvider": "mock",
  "providerToken": "tok_4242_visa_1230",
  "cardSummary": {
    "brand": "visa",
    "last4": "4242",
    "expMonth": 12,
    "expYear": 2030,
    "country": "SG"
  }
}
```

Note what is NOT in the request: `cardNumber`, `cvv`, `cardholderName`. These never enter the public API surface. Production architecture assumes the channel layer (mobile app, web portal) uses a PCI-compliant client-side tokenizer (Stripe Elements, Adyen Web Drop-in, Checkout.com Frames) and hands BSS-CLI only the resulting token. BSS-CLI never sees a PAN in production, even by accident.

### 4. Mock tokenizer — `app/domain/mock_tokenizer.py`

Lives in `domain/`, not `services/`. Pure functions, no DB, no HTTP. Only invoked from tests and from the dev CLI (gated behind `BSS_ENABLE_DEV_TOKENIZER=true`). Never from the public API.

```python
# ============================================================================
#  SANDBOX ONLY — NEVER STORE PAN OR CVV IN A REAL SYSTEM
#
#  In production, card numbers go directly from the client (mobile app, web
#  portal) to a PCI-compliant tokenization service (Stripe, Adyen, Checkout.com,
#  etc). The backend ONLY ever sees the resulting token.
#
#  This mock tokenizes server-side PURELY for demo simplicity and MUST NOT
#  be used as a production pattern. The public POST /paymentMethod endpoint
#  takes a pre-tokenized request — this module is only invoked from tests
#  and from `bss payment add-card` in dev mode (gated behind
#  BSS_ENABLE_DEV_TOKENIZER).
# ============================================================================

def tokenize_card(card_number: str, exp_month: int, exp_year: int, cvv: str) -> TokenizeResult:
    # Returns tok_<uuid4>, last4, brand from BIN
    # Brand: 4xxx → visa, 51–55xx → mastercard, 34/37 → amex
    # card_number containing "FAIL" → token that will decline at charge time
    # Expired card raises ValidationError
    ...

async def charge(token: str, amount: Decimal, currency: str) -> ChargeResult:
    await asyncio.sleep(0.05)  # simulate latency
    if "FAIL" in token or "DECLINE" in token:
        return ChargeResult(status="declined", reason="card_declined_by_issuer", ...)
    if amount <= 0:
        raise ValueError("amount must be positive")
    return ChargeResult(status="approved", gateway_ref=f"mock_{uuid4()}")
```

The PCI warning comment is **non-negotiable** — verbatim or near-verbatim at the top of the file. Reviewers grep for "SANDBOX ONLY" during verification.

### 5. `packages/bss-clients/` — shared HTTP client package

Created in this phase, used by every service from Phase 6 onwards, and by the CLI orchestrator in Phase 9.

```
packages/bss-clients/
├── pyproject.toml
├── bss_clients/
│   ├── __init__.py
│   ├── base.py         # AsyncClient base: timeouts, typed errors, auth provider hook
│   ├── errors.py       # ClientError, NotFound, PolicyViolationFromServer, ServerError
│   ├── auth.py         # AuthProvider protocol + NoAuthProvider default
│   ├── crm.py          # CRMClient: get_customer, get_kyc_status
│   ├── catalog.py      # CatalogClient: get_offering, list_offerings
│   └── payment.py      # PaymentClient: charge, get_method (scaffold for Phase 6)
└── tests/
    ├── test_base_errors.py
    ├── test_crm_client.py
    ├── test_auth_provider.py
    └── test_header_propagation.py
```

**Design rules (non-negotiable):**

1. **Timeouts are mandatory and per-method.** Default 5s, overridable per call. No infinite waits.
2. **No automatic retries.** A 503 from a downstream is a fact — the caller decides. LangGraph (Phase 9) handles orchestration-level retries separately.
3. **Typed errors.** `NotFound` ≠ `ServerError` ≠ `PolicyViolationFromServer`. Callers `except` on what they handle.
4. **Header propagation.** Every outgoing call carries `X-BSS-Actor`, `X-BSS-Channel`, `X-Request-ID` from `auth_context.current()`. This is what makes the audit trail honest across service boundaries.
5. **AuthProvider is pluggable.** Every client takes an `AuthProvider` at construction. v0.1 uses `NoAuthProvider` (returns empty auth headers). Phase 12 swaps in `OAuth2ClientCredentialsProvider`. **Do not hardcode "no auth" anywhere else in the codebase** — use the abstraction even though it's a no-op. This is the Phase 12-ready seam.
6. **Structured PolicyViolation parsing.** When a downstream returns HTTP 422 with a `code: POLICY_VIOLATION` body, the client raises `PolicyViolationFromServer(rule=..., message=..., context=...)`. Callers branch on the rule ID, not on JSON parsing.

### 6. Cross-service contract — Payment → CRM

Payment calls `CRMClient.get_customer(customer_id)` when registering a new payment method. First real cross-service HTTP call in the project.

```python
# services/payment/app/policies/payment_method.py
@policy("payment_method.add.customer_exists")
async def check_customer_exists(customer_id: str, crm_client: CRMClient):
    try:
        await crm_client.get_customer(customer_id)
    except NotFound:
        raise PolicyViolation(
            rule="payment_method.add.customer_exists",
            message=f"Customer {customer_id} does not exist",
            context={"customer_id": customer_id},
        )
```

**No shared DB access between services.** Payment does NOT query `crm.customer` directly. Ever.

## Policies required this phase

- [ ] `payment_method.add.customer_exists` — cross-service via CRMClient
- [ ] `payment_method.add.customer_active_or_pending` — cross-service, checks `status` and `kyc_status` from CRM response
- [ ] `payment_method.add.card_not_expired` — validates `expMonth`/`expYear` in request
- [ ] `payment_method.add.at_most_n_methods` — limit 5 per customer for v0.1
- [ ] `payment_method.remove.not_last_if_active_subscription` — stub in Phase 5 (real check wired in Phase 6 via `SubscriptionClient`)
- [ ] `payment.charge.method_active` — method status must be `active`, not `removed`
- [ ] `payment.charge.positive_amount`
- [ ] `payment.charge.customer_matches_method`

## Events published

- `payment_method.added`, `payment_method.removed`
- `payment.charged`, `payment.declined`, `payment.errored`

All via the shared `bss-events` package. All persist to `audit.domain_event` in the same transaction as the domain write.

## Test strategy

Phase 4 shipped three bugs (camelCase alias broken, in-memory counters, missing routes) because the test suite called service methods with snake_case dicts, bypassing the HTTP layer entirely. Phase 5 does not repeat this.

### Mandatory coverage rules (from DECISIONS.md Phase 4 lessons)

1. **Every router endpoint has at least one `httpx.AsyncClient` test with a camelCase JSON body.** Service-layer tests are fine for policy and pure logic, but they do not prove the API contract. camelCase aliases, required-field validation, and route wiring are only verified by HTTP-level tests.

2. **ID generation must survive restart.** No module-level counters. Use Postgres sequences. A test must reload the FastAPI app factory (simulating restart) and verify no PK collision.

### Cross-service test strategy — new in Phase 5

Hybrid approach. Document in `DECISIONS.md` under the Phase 5 entry as the pattern for all future phases:

- **Happy path: real CRM container.** Tests assume CRM is up (from `docker compose up -d crm`), exercise the real network path. Catches "forgot the docker network", "wrong port", "wrong DNS", container env issues, and similar integration bugs.
- **Error paths: `respx` library.** Register fake responses for specific URLs. Tests say "if Payment's CRMClient calls `GET http://crm:8002/customer/CUST-999`, return 404 with this body." Lets you exercise the `customer_exists` violation, "CRM is down" (503), and malformed response handling — none of which CRM will fake for you on demand.

### Required test files

- `test_mock_tokenizer.py` — pure-function unit tests (no DB, no HTTP)
- `test_payment_method_api.py` — httpx tests for every `/paymentMethod` endpoint with camelCase JSON bodies
- `test_payment_api.py` — httpx tests for `/payment` charge endpoint, happy path and decline path
- `test_payment_crm_integration.py` — real CRM container, happy path for customer lookup
- `test_payment_crm_failures.py` — respx-mocked CRM returning 404 / 503 / malformed
- `test_policies.py` — direct policy unit tests with injected mocks
- `test_bss_clients_base.py` — timeouts, typed errors, no-auto-retry behavior
- `test_bss_clients_auth.py` — `NoAuthProvider` default, custom `AuthProvider` invoked on every call
- `test_bss_clients_headers.py` — `X-BSS-Actor`/`X-BSS-Channel`/`X-Request-ID` propagated from `auth_context`
- `test_id_sequences.py` — create two methods, simulate app restart, create a third, assert no PK collision

## ID generation

Postgres sequences for `PM-xxx` and `PAY-xxx`. Module-level counters are banned per DECISIONS.md Phase 4 lesson.

```sql
CREATE SEQUENCE payment.payment_method_id_seq;
CREATE SEQUENCE payment.payment_attempt_id_seq;
```

Format: `PM-{nextval:04d}` and `PAY-{nextval:06d}` in application code. Sequences go in an Alembic migration.

## Docker

- `docker-compose.yml` adds `payment` on port 8003, same env var pattern as crm
- Use whatever Dockerfile pattern Phase 4 settled on (shared template or per-service) — do NOT regress from the Phase 4 Dockerfile fix
- `docker compose build --no-cache payment catalog crm` must succeed clean

## Verification checklist

- [ ] `make up` brings up payment alongside catalog and crm
- [ ] `POST /paymentMethod` with a pre-tokenized request returns 201; response has `providerToken`, `last4`, `brand`; no PAN fields
- [ ] `docker compose logs payment 2>&1 | grep 4242424242424242` returns **zero hits**
- [ ] `grep -r "SANDBOX ONLY" services/payment/app/domain/` finds the PCI warning comment
- [ ] `POST /paymentMethod` for unknown customer → HTTP 422, body contains `rule: payment_method.add.customer_exists`, call routed through real CRM container
- [ ] `POST /paymentMethod` with expired card → HTTP 422, rule `payment_method.add.card_not_expired`
- [ ] `POST /payment` with amount 10.00 SGD → approved, payment row created
- [ ] `POST /payment` using a method whose token contains `"FAIL"` → `status=declined` (HTTP 200, not 4xx — declines are business outcomes)
- [ ] `DELETE /paymentMethod/{id}` → method marked removed, emits `payment_method.removed`
- [ ] Both approved and declined charges emit correct events and audit rows
- [ ] `bss-clients` tests pass including auth provider hook and header propagation
- [ ] All tests pass via `make test`: catalog + crm + payment suites, no regression
- [ ] Campaign OS schemas untouched (`bsspsql -c "SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema IN ('campaignos', 'public') GROUP BY table_schema;"` → same as before phase)
- [ ] `docker compose build --no-cache payment` builds clean
- [ ] ID counter survives restart: create two methods, restart payment container, create a third, verify no PK collision

## Out of scope

- Real tokenization
- 3DS simulation
- Refunds
- Multiple currencies (SGD only)
- Partial captures
- Saved customer profiles on gateway
- Real AuthProvider implementation (Phase 12)
- `SubscriptionClient` cross-service calls (Phase 6)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `TOOL_SURFACE.md`, `DECISIONS.md`, and `phases/PHASE_05.md`. Read `services/crm/` as the service pattern reference (clone its structure, `auth_context.py`, `config.py` with `_REPO_ROOT`, middleware). Read the Phase 4 entries in `DECISIONS.md` on API-level test coverage and ID generation surviving restart.
>
> Before writing any code, produce a plan that includes:
>
> 1. **Service layout** — exact directory tree for `services/payment/`, matching Phase 4 CRM structure.
>
> 2. **`bss-clients` package layout** — exact file tree for `packages/bss-clients/`, including `AuthProvider` protocol, `NoAuthProvider` default, and the three service client classes (`CRMClient`, `CatalogClient`, `PaymentClient`). Confirm `PolicyViolationFromServer` parses downstream 422 bodies into typed exceptions.
>
> 3. **Public API takes tokens, not cards.** Paste the `PaymentMethodCreateRequest` Pydantic schema and confirm `cardNumber` and `cvv` fields do not exist. Confirm the `POST /paymentMethod` handler never calls `mock_tokenizer.tokenize_card()` — that function is only invoked from tests and from the dev CLI gated behind `BSS_ENABLE_DEV_TOKENIZER`.
>
> 4. **PCI warning comment** — paste the exact comment you will place at the top of `mock_tokenizer.py`. It must explicitly say "SANDBOX ONLY", must say "MUST NOT be used as a production pattern", and must explain where real tokenization happens.
>
> 5. **Mock tokenizer signature and behavior** — confirm pure functions (no DB, no HTTP), BIN-based brand detection, "FAIL"/"DECLINE" special-case for tokens that should decline at charge.
>
> 6. **Policy catalog** — all 8 policies: rule ID, module, negative test case. Flag which are stubs (`payment_method.remove.not_last_if_active_subscription` is stubbed in Phase 5, real in Phase 6).
>
> 7. **Cross-service test strategy** — confirm the hybrid (real CRM container for happy path, respx for failures). List the test files and what each covers. Confirm this will be recorded in DECISIONS.md as the pattern for Phase 6+.
>
> 8. **ID generation** — Postgres sequences for `PM-xxx` and `PAY-xxx`, not module-level counters. Paste the `CREATE SEQUENCE` DDL.
>
> 9. **AuthProvider hook** — paste the `AuthProvider` protocol and `NoAuthProvider` default. Confirm every client takes an `AuthProvider` at construction and calls it on every outgoing request. No hardcoded auth headers anywhere else.
>
> 10. **Test coverage** — confirm every router endpoint has at least one `httpx.AsyncClient` test with a camelCase JSON payload (Phase 4 lesson). Confirm `bss-clients` base has tests for timeouts, typed errors, and header propagation.
>
> Wait for my approval before writing any code.
>
> After I approve, implement in this order:
> 1. `packages/bss-clients/` — base, errors, auth protocol, NoAuthProvider, CRMClient (only `get_customer` needed this phase)
> 2. `services/payment/app/domain/mock_tokenizer.py` with the PCI warning comment
> 3. `services/payment/app/policies/` — all 8 policies
> 4. `services/payment/app/repositories/` — payment_method, payment_attempt
> 5. `services/payment/app/services/` — PaymentMethodService, PaymentService
> 6. `services/payment/app/schemas/` — TMF676 camelCase + internal DTOs
> 7. `services/payment/app/api/` — routers, no business logic
> 8. `services/payment/app/events/publisher.py`
> 9. Tests in order: tokenizer → bss-clients base → auth provider → policy → repository → API (httpx) → cross-service integration (real CRM) → cross-service failure (respx) → ID sequence restart
> 10. Alembic migration for sequences
> 11. `docker-compose.yml` — add payment on port 8003
>
> After implementation, run the verification checklist. Run `make test` for all suites. Run `docker compose logs payment 2>&1 | grep 4242424242424242` (expect zero). Run `docker compose build --no-cache payment` (expect clean). Query Campaign OS schemas (expect untouched). Paste results as a Markdown table. Do not commit.

## The trap

**Don't let Claude Code build a real tokenization flow.** The mock is the point. If `mock_tokenizer.py` exceeds ~150 lines total, it's drifting. Push back.

**Don't accept the plan without the PCI comment pasted verbatim.** That comment is documentation for every future reader and is non-negotiable. If Claude Code's plan says "will add standard PCI warning" without pasting the actual text, ask for the exact text.

**Don't let `AuthProvider` logic leak anywhere except `bss-clients/auth.py`.** If you see `headers["Authorization"] = ...` anywhere else, Phase 12 retrofit becomes hard.

**Don't let Claude Code skip the hybrid test strategy.** "I'll just use respx for everything" misses the point of proving cross-service calls work on the wire. "I'll just use the real CRM for everything" can't simulate failures. Both, as specified.
