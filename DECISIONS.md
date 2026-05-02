# DECISIONS.md — BSS-CLI Architecture Decision Log

This file records non-obvious decisions. Every Claude Code session appends here when making a choice that isn't trivial. Future sessions read this to stay consistent.

## Format

```
## YYYY-MM-DD — Phase N — Title
**Context:** what prompted the decision
**Decision:** what we chose
**Alternatives:** what we rejected and why
**Consequences:** what this makes easier/harder
```

---

## Foundational decisions (established Phase 0, permanent)

These are the core architectural choices that shape the entire project. They are not historical — they remain in force across every phase and every future version unless explicitly retired in a subsequent DECISIONS entry.

### 2026-04-11 — Phase 0 — Case/Ticket model is ServiceNow-shaped
**Context:** CRM cases and tickets can be flat (Zendesk-style) or hierarchical (ServiceNow-style).
**Decision:** Case is top-level container, Case has 1..N Tickets.
**Alternatives:** Zendesk-style — rejected because it doesn't match telco CRM reality (Siebel, Salesforce Comms Cloud).
**Consequences:** Closing a Case requires all child Tickets resolved. Natural context anchor for LLM actions.

### 2026-04-11 — Phase 0 — SOM uses proper hierarchical decomposition, minimal cardinality
**Context:** SOM modeling depth tradeoff.
**Decision:** Proper COM → SOM → CFS → RFS → Resource decomposition, but 1 CFS + 2 RFS per plan in v0.1.
**Alternatives:** Flat SOM — loses educational value. Multi-CFS per plan — v0.2.
**Consequences:** TMF641/638 shapes are real. State space tractable. Adding more CFS later is mechanical.

### 2026-04-11 — Phase 0 — Provisioning simulator has configurable failure scenarios
**Context:** Simulator fidelity level.
**Decision:** Time delays + per-task-type fault injection + "stuck" state for manual resolution.
**Alternatives:** Pure random failure (too simplistic); full fake NE (project within a project).
**Consequences:** Scenarios deliberately trigger failures. `bss trace` swimlanes show meaningful interactions.

### 2026-04-11 — Phase 0 — Write Policy doctrine (no raw CRUD)
**Context:** LLM write access without data corruption risk.
**Decision:** Every write flows through per-service policy layer. Router → Service → Policies → Repository → Event publisher.
**Alternatives:** Trust LLM + rollback (referential corruption is silent); DB constraints only (domain invariants don't map to constraints).
**Consequences:** More code per service. Every write phase adds policies to this file. LLM can be trusted with writes.

### 2026-04-11 — Phase 0 — RabbitMQ is the async plane, HTTP the sync plane
**Context:** Initial diagram conflated MQ with DB writes.
**Decision:** RabbitMQ = pub/sub between services for reactions. HTTP = direct calls for immediate answers. Postgres = per-service writes, not via MQ. Audit table + post-commit publish = simplified outbox.
**Alternatives:** Everything-via-events (loses sync call ergonomics); everything-via-HTTP (loses fanout and decoupling).
**Consequences:** Clear mental model. Services declare which plane each call uses. Replay via audit table. Event ordering is not strict across routing keys — policy checks enforce causality.

### 2026-04-11 — Phase 0 — eSIM-only inventory
**Context:** Physical SIM involves warehousing, courier integration, activation-on-first-use semantics.
**Decision:** eSIM-only for v0.1. New provisioning task `ESIM_PROFILE_PREPARE`. SOM reserves MSISDN + eSIM profile atomically. Customer receives LPA activation code + ASCII QR code.
**Alternatives:** Physical + eSIM dual-track — eliminates from v0.1 as unnecessary complexity.
**Consequences:** No logistics layer. `inventory.esim_profile` table with ki_ref (NEVER raw Ki). Modern MVNO default.

### 2026-04-11 — Phase 0 — eKYC is a channel-layer concern
**Context:** eKYC involves document capture, liveness, biometrics, government integration — all jurisdiction-specific.
**Decision:** BSS-CLI receives signed KYC attestations via `customer.attest_kyc`. Document numbers stored as SHA-256 hashes. Full plaintext lives in the attesting system or nowhere. Channel layer (mobile app, portal) runs the actual eKYC flow with Myinfo/Jumio/Onfido.
**Alternatives:** Build eKYC into CRM — makes BSS jurisdiction-coupled and instantly obsolete when crossing borders.
**Consequences:** Clean separation of concerns. `kyc_status` column on customer, `customer_identity` table for attestation. Policy `order.create.requires_verified_customer` enforceable via env flag.

### 2026-04-11 — Phase 0 — Inventory domain hosted inside CRM service (v0.1)
**Context:** Inventory could be a separate service or embedded.
**Decision:** MSISDN + eSIM pools live inside CRM service as a separate domain (own schema, repositories, policies). Not a separate container in v0.1.
**Alternatives:** 11th service — adds network hop in critical path, adds ~150MB RAM, saves almost nothing operationally.
**Consequences:** 10 containers total. Inventory is extractable in v0.2 if needed — schema boundary is already enforced. SOM and Subscription call inventory via `bss-clients` as if it were a distinct service, so extraction requires zero caller-side code changes.

### 2026-04-11 — Phase 0 — Single Postgres instance, schema-per-domain
**Context:** 11 schemas could be one instance or many.
**Decision:** ONE PostgreSQL 16 instance with 11 schemas. Each service has its own `BSS_DB_URL` and uses only its own schema.
**Alternatives:** One instance per service — blows RAM budget (~4.4GB), operational complexity too high for v0.1.
**Consequences:** Simpler ops, simpler outbox pattern, fits in 4GB. Future split by schema is mechanical — no service code changes. Co-tenanting with non-BSS schemas (e.g., `campaignos` in dev) works because each service's migration is schema-scoped, not database-scoped.

### 2026-04-11 — Phase 0 — Container structure: 10 services, infra optional (BYOI default)
**Context:** How to package for deployment.
**Decision:** Default `docker-compose.yml` contains ONLY 10 BSS services. Separate `docker-compose.infra.yml` brings up Postgres, RabbitMQ, Metabase for all-in-one dev/demo. Most operators bring their own managed infra, and BSS-CLI development has run BYOI from Phase 1 onwards against an external Postgres on tech-vm.
**Alternatives:** Single compose with everything — forces Postgres/MQ even when deployer has managed services.
**Consequences:** BYOI is the default shape and the primary development mode. All-in-one is opt-in via `-f docker-compose.infra.yml`. Maps cleanly to ECS/EKS where each service is a task/pod with env-driven connection strings.

### 2026-04-11 — Phase 0 — auth_context abstraction in every service for Phase 12 readiness
**Context:** v0.1 ships without auth; retrofitting auth later risks touching every service.
**Decision:** Every service has `app/auth_context.py` that returns a hardcoded `AuthContext(actor='system', tenant='DEFAULT', roles=['admin'], permissions=['*'])`. All policies and tool dispatches read from `auth_context.current()`. Phase 12 changes only this one module per service plus middleware.
**Alternatives:** Retrofit when needed — would touch every policy function and every router.
**Consequences:** ~30 minutes added to Phase 3 reference slice. Phase 12 becomes a decorator-layer concern. Same pattern extended to `bss-clients` in Phase 5 via `AuthProvider` protocol + `NoAuthProvider` default.

### 2026-04-11 — Phase 0 — Runbook RAG deferred to Phase 11
**Context:** LLM procedural knowledge (runbooks) needs a knowledge base.
**Decision:** v0.1 ships with `docs/runbooks/` directory seeded with 3-4 markdown files but NO embedding/retrieval. Phase 11 adds `pgvector` extension to existing Postgres, `knowledge` schema, `knowledge.search` tool. BGE-small for embeddings (384-dim, local, PDPA-safe).
**Alternatives:** Dedicated vector DB (Qdrant) — extra container, blows footprint. LLM Wiki pattern — version control is weaker than git.
**Consequences:** Zero v0.1 scope cost. Runbook content can be drafted in parallel to code. Phase 11 is additive.

### 2026-04-11 — Phase 0 — AWS deployment path: ECS Fargate for Tier 1/2, EKS for Tier 3
**Context:** MVNO deployability on AWS.
**Decision:** v0.1 containers are ECS-Fargate-ready out of the box. Tier 1 (~$400/mo) is a direct compose→ECS translation. Tier 2 (~$1000/mo) adds Multi-AZ RDS, active/standby Amazon MQ, min 2 tasks per service. Tier 3 (100k+ subs, ~$5000/mo) switches to EKS + Aurora + MSK.
**Alternatives:** EKS from day 1 — overkill for small MVNO, higher operational burden.
**Consequences:** Zero v0.1 code changes needed for AWS Tier 1. Phase 12 (auth) is the gating dependency for Tier 2 (production).

---

## Initial policy catalog

> **Note:** this catalog was drafted during Phase 0 as the planned v0.1 policy surface. For the authoritative current state of each policy (implemented, stubbed, or retired), see the per-phase running log entries below. When the catalog drifts significantly from reality, this section should be extracted to a dedicated `POLICIES.md` file — tracked as a Phase 11 backlog item.

### CRM — customer + KYC
- `customer.create.email_unique` — globally unique email across active customers
- `customer.create.requires_contact_medium` — at least one email OR phone
- `customer.close.no_active_subscriptions`
- `customer.attest_kyc.customer_exists`
- `customer.attest_kyc.attestation_signature_valid` — stub in v0.1
- `customer.attest_kyc.document_hash_unique_per_tenant`

### CRM — case
- `case.open.customer_must_be_active`
- `case.transition.valid_from_state`
- `case.close.requires_all_tickets_resolved`
- `case.close.requires_resolution_code`
- `case.add_note.case_not_closed`

### CRM — ticket
- `ticket.open.requires_customer_or_case`
- `ticket.assign.agent_must_be_active`
- `ticket.transition.valid_from_state`
- `ticket.resolve.requires_resolution_notes`
- `ticket.cancel.not_if_resolved_or_closed`

### Inventory
- `msisdn.reserve.status_must_be_available`
- `esim.reserve.status_must_be_available`
- `esim.release.only_if_reserved_or_assigned`

### Payment
- `payment_method.add.customer_exists`
- `payment_method.add.customer_active_or_pending`
- `payment_method.add.card_not_expired`
- `payment_method.add.at_most_n_methods`
- `payment_method.remove.not_last_if_active_subscription`
- `payment.charge.method_active`
- `payment.charge.positive_amount`
- `payment.charge.customer_matches_method`

### COM
- `order.create.customer_active_or_pending`
- `order.create.requires_cof`
- `order.create.requires_verified_customer` — gated by `BSS_REQUIRE_KYC` env var, default OFF in v0.1
- `order.create.offering_sellable`
- `order.cancel.forbidden_after_som_started`
- `order.transition.valid_from_state`

### SOM
- `service_order.create.requires_parent_order`
- `service_order.create.mapping_exists`
- `service.activate.requires_all_rfs_activated`
- `service.terminate.releases_msisdn_and_esim`
- `service.transition.valid_from_state`

### Provisioning
- `provisioning_task.retry.max_attempts`
- `provisioning.resolve_stuck.requires_note`
- `provisioning.set_fault_injection.admin_only`

### Subscription
- `subscription.create.requires_customer`
- `subscription.create.requires_payment_success`
- `subscription.create.msisdn_and_esim_reserved`
- `subscription.vas_purchase.requires_active_cof`
- `subscription.vas_purchase.vas_offering_sellable`
- `subscription.vas_purchase.not_if_terminated`
- `subscription.renew.only_if_active_or_blocked`
- `subscription.terminate.releases_msisdn`
- `subscription.terminate.recycles_esim`
- `subscription.terminate.cancels_pending_vas`

### Billing
- `bill.issue.subscription_exists`
- `bill.issue.period_not_already_billed`

### Usage / Mediation / Rating
- `usage.record.subscription_must_exist`
- `usage.record.subscription_must_be_active` — blocked → reject at ingress
- `usage.record.positive_quantity`
- `usage.record.valid_event_type`
- `usage.record.msisdn_belongs_to_subscription`
- `rating.tariff_must_exist_for_offering`

---

## Running log

_Claude Code appends below this line as phases progress._

### 2026-04-11 — Phase 3 — Config.py reads .env via pydantic-settings env_file with _REPO_ROOT
**Context:** Phase 3 verification revealed that `uv run pytest` does not inherit shell-exported `.env` variables. A shell-level `set -a; source .env; set +a` workaround unblocks local tests but is fragile and breaks in CI, IDE test runners, and any invocation where cwd is not the service directory.
**Decision:** Every service's `config.py` computes `_REPO_ROOT = Path(__file__).resolve().parents[3]` and passes `env_file=_REPO_ROOT / ".env"` to `SettingsConfigDict`. pydantic-settings reads `.env` directly from the repo root regardless of cwd or shell environment.
**Alternatives:** (a) Relative path `env_file="../../.env"` — works from the service directory but fails from the repo root; breaks `make test`. (b) Export in Makefile and rely on recipe inheritance — works for `make test` but not for direct `uv run pytest`, IDE, CI. (c) Require `source .env` before every command — dev friction, silently breaks in CI.
**Consequences:** Services read `.env` uniformly from any invocation context. Pattern is part of the service template cloned in Phases 4-10. Shipped as chore commit `chore: config.py reads .env via pydantic-settings env_file` on main after Phase 3 merge. Applied to both `services/_template/app/config.py` and `services/catalog/bss_catalog/config.py`. Phases 4+ inherit the fix via template clone.

### 2026-04-11 — Phase 4 — Case state machine (narrowed cancel)
**Context:** Original spec allowed cancel from "any except closed", including resolved. Resolved cases should only proceed to closed, not be cancelled.
**Decision:** Cancel valid only from `{open, in_progress, pending_customer}`. Resolved → closed via explicit close trigger only.
**Alternatives:** Cancel from any non-terminal — rejected because resolved cases have completed work; cancelling them misrepresents outcome.
**Consequences:** Cleaner audit trail. Resolved cases always close, never cancel.

#### Case transitions

| From | Trigger | To | Guard / Action |
|---|---|---|---|
| open | take | in_progress | action: log_interaction |
| in_progress | await_customer | pending_customer | — |
| pending_customer | resume | in_progress | — |
| in_progress | resolve | resolved | guard: all_tickets_resolved |
| open | resolve | resolved | guard: no_tickets OR all_resolved |
| resolved | close | closed | guard: resolution_code_set |
| open, in_progress, pending_customer | cancel | closed | action: cancel_open_tickets |

### 2026-04-11 — Phase 4 — Ticket state machine

| From | Trigger | To | Guard / Action |
|---|---|---|---|
| open | ack | acknowledged | guard: assigned_agent |
| acknowledged | start | in_progress | — |
| in_progress | wait | pending | — |
| pending | resume | in_progress | — |
| in_progress | resolve | resolved | guard: resolution_notes |
| resolved | close | closed | — |
| resolved | reopen | in_progress | — |
| open, acknowledged, in_progress, pending | cancel | cancelled | — |

Terminal states: closed, cancelled.

### 2026-04-11 — Phase 4 — eSIM profile lifecycle

| From | Trigger | To | Guard / Action |
|---|---|---|---|
| available | reserve | reserved | atomic SELECT FOR UPDATE SKIP LOCKED |
| reserved | assign_msisdn | reserved | sets assigned_msisdn |
| reserved | download | downloaded | customer scans QR |
| downloaded | activate | activated | first attach on HLR |
| activated | suspend | suspended | subscription blocked |
| suspended | activate | activated | reactivation |
| activated | recycle | recycled | 90-day cooldown |
| reserved | release | available | cancelled order path |

### 2026-04-11 — Phase 4 — Test isolation: per-test transactional rollback
**Context:** CRM is the first write-heavy service. Tests must not pollute the shared tech-vm DB.
**Decision:** Each test gets a DB connection with an outer transaction. All writes within the test (including nested `session.begin()` calls, which become savepoints) are rolled back in teardown. The client fixture injects this session into the app.
**Alternatives:** (a) Per-test savepoint — mechanically identical, naming difference. (b) Dedicated test schema with migrations — overkill, slow setup, no benefit over rollback.
**Consequences:** Zero DB pollution. Tests can run in parallel per-session. No extra infrastructure.

### 2026-04-11 — Phase 4 — Dropped case.add_note.case_not_closed policy
**Context:** Whether to add a policy preventing notes on closed cases.
**Decision:** Drop. The state machine prevents mutations on closed cases. Adding a redundant policy check on an append-only operation adds noise.
**Consequences:** One fewer policy to test. If needed later, enforce at state machine level.

### 2026-04-11 — Phase 4 — ticket.open policy renamed for clarity
**Context:** Original policy `ticket.open.requires_customer_or_case` was ambiguous — did it mean "either/or"?
**Decision:** Rename to `ticket.open.requires_customer`. Meaning: `customer_id` is required (NOT NULL), `case_id` is optional. Standalone tickets are allowed.
**Consequences:** Clearer semantics. Matches DATA_MODEL.md where customer_id is NOT NULL on ticket.

### 2026-04-11 — Phase 4 — Per-service Dockerfile with workspace sed workaround
**Context:** uv workspace dependency `bss-models = { workspace = true }` does not resolve inside a Docker build context because the build context only contains the service subtree, not the workspace root `pyproject.toml`. The shared template Dockerfile described in ARCHITECTURE.md (`uv sync --package ${SERVICE}`) fails with "bss-models references a workspace but is not a workspace member".
**Decision:** Each service has its own Dockerfile that rewrites the workspace reference to a relative path before running `uv pip install`:
```dockerfile
RUN sed -i 's|workspace = true|path = "../../packages/bss-models"|' pyproject.toml \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python .
```
**Alternatives:** (a) Shared template Dockerfile copying workspace root pyproject.toml and uv.lock: works but rebuilds every service whenever workspace root changes, harder cache invalidation. (b) Publish bss-models to a local PyPI mirror: too much infrastructure for v0.1. (c) Monorepo build orchestration tool (Bazel, Pants, Nx): massive scope creep, kills motto #6.
**Consequences:** Each new service clones catalog's Dockerfile pattern. Migration to workspace-aware builds is tracked as a Phase 11 backlog item — worth revisiting when `uv` matures workspace-aware `sync` inside build contexts, or when the service count makes duplication painful. ARCHITECTURE.md documents both the current expedient and the intended long-term shape.

### 2026-04-11 — Phase 4 — Hybrid cross-service test strategy
**Context:** Phase 5 will introduce cross-service HTTP calls (Payment → CRM for `customer_exists` policy check). Unit-test strategy must cover both real-wire happy paths and simulated failure modes. Neither approach alone is sufficient.
**Decision:** Hybrid approach. **Happy path:** real downstream container started via `docker compose up -d`, test exercises the real HTTP wire end-to-end. Catches docker networking, service discovery, env variable, and container health issues. **Error paths:** `respx` library registers canned responses for specific URLs, letting tests simulate 404 / 422 / 503 / malformed-body / timeout responses that real CRM will never produce on demand.
**Alternatives:** (a) respx-only — can't prove docker networking or service discovery works; container-level integration bugs only surface at scenario runtime. (b) Real-only — can't simulate failures without contriving fault injection in the downstream service, which bloats its test surface. (c) In-process ASGI test client mounted on a fake CRM app — middle ground, but adds another moving part and still doesn't exercise real HTTP.
**Consequences:** Every service from Phase 5 onward uses this pattern. Each cross-service dependency gets two test files per consumer: `test_<service>_<downstream>_integration.py` (real container) and `test_<service>_<downstream>_failures.py` (respx). Slightly more setup per service, but real protection against both integration and error-handling bugs. Documented in Phase 5 reworked spec as mandatory.

### 2026-04-11 — Phase 4 — API tests must exercise the HTTP layer, not service methods

**Context:** Phase 4 shipped with three bugs that 60 pytest tests did not catch:
1. `contactMedium` camelCase alias was broken — tests called service methods with snake_case Python dicts, bypassing the Pydantic alias layer entirely. Real HTTP callers would have hit 500s.
2. In-memory ID counters reset on app restart, causing PK collisions. No test exercised restart behavior.
3. Ticket transitions `ack`, `start`, `close` existed in the service layer but had no HTTP routes. Tests only exercised `resolve` and `cancel`.

**Decision:** Every service test suite must enforce three rules:

1. **Every endpoint has at least one httpx AsyncClient test with a JSON payload.** Service-layer tests are fine for policy and state machine logic but do not prove the API contract. camelCase aliases, required-field validation, and route wiring are only verified by HTTP-level tests.

2. **Every state machine transition has a parametrized API test.** Use `pytest.mark.parametrize` over the transitions table from `DECISIONS.md`. If a transition exists in the table but has no HTTP route, the test fails at collection time. This catches missing-route bugs automatically.

3. **ID generation must survive restart.** Use database sequences or UUIDs — never module-level counters. Any test fixture that reuses the FastAPI app factory (without full container restart) is sufficient to catch counter-based bugs.

**Consequences:** Slightly larger test suites per service, test-time round-trips through the full HTTP stack (~2ms overhead per test), and real protection against TMF serialization, routing, and persistence bugs. These are the kinds of bugs that otherwise only surface during Phase 10 hero scenarios when the cost of finding them is highest.

### 2026-04-11 — Phase 5 — bss-clients: typed errors, no auto-retry, AuthProvider protocol
**Context:** Phase 5 introduces the first cross-service HTTP call (Payment → CRM). Need a shared HTTP client package that enforces consistent error handling, header propagation, and auth readiness across all services.
**Decision:** `packages/bss-clients` provides `BSSClient` base class with: (1) typed error mapping (404→NotFound, 422+POLICY_VIOLATION→PolicyViolationFromServer, 5xx→ServerError, timeout→Timeout), (2) NO auto-retry (caller decides), (3) `AuthProvider` protocol with `NoAuthProvider` default for Phase 12 readiness, (4) context header propagation via `contextvars` (`X-BSS-Actor`, `X-BSS-Channel`, `X-Request-ID`).
**Alternatives:** (a) Raw httpx per service — duplicates error mapping, header injection, timeout config. (b) Auto-retry with backoff — violates CLAUDE.md doctrine ("no retries inside tool functions; LangGraph supervisor handles retries"). (c) Shared middleware-only approach — doesn't cover outgoing headers or auth.
**Consequences:** Every downstream client (CRM, Catalog, Payment) extends `BSSClient`. Actor chain is proven end-to-end via respx test. Phase 12 auth is a one-line change per client constructor.

### 2026-04-11 — Phase 5 — Payment API is pre-tokenized (no PAN/CVV on the wire)
**Context:** PCI DSS compliance requires that cardholder data never transit the BSS API surface.
**Decision:** `PaymentMethodCreateRequest` accepts `providerToken`, `tokenizationProvider`, and `cardSummary` (brand, last4, expMonth, expYear). No `cardNumber` or `cvv` field exists. The mock tokenizer (`mock_tokenizer.py`) is internal-only with a prominent PCI SANDBOX warning. Real deployments use a channel-layer tokenizer (Stripe, Adyen).
**Alternatives:** Accept PAN and tokenize server-side — creates PCI scope on every BSS service, unacceptable.
**Consequences:** BSS-CLI is out of PCI DSS scope for cardholder data. Mock tokenizer exists only for dev/test. Production token lifecycle is a channel-layer concern.

### 2026-04-11 — Phase 5 — Middleware catches upstream ServerError for clean 500 responses
**Context:** When CRM returns 503, `bss-clients` raises `ServerError`. Starlette's `BaseHTTPMiddleware` re-raises exceptions before FastAPI's default handler can catch them, causing raw exception propagation through the ASGI transport.
**Decision:** Payment middleware catches `ServerError` explicitly and returns `JSONResponse(500, {"detail": "Upstream service error"})`.
**Alternatives:** (a) Register a FastAPI `exception_handler` — doesn't fire for exceptions raised inside `BaseHTTPMiddleware.dispatch`. (b) Don't use BaseHTTPMiddleware — requires refactoring to pure ASGI middleware, larger change for same effect.
**Consequences:** Upstream failures produce clean JSON 500s. Pattern extends to future services. Error detail is intentionally opaque to avoid leaking upstream internals.

### 2026-04-11 — Phase 5 — ASGI test fixtures must mirror lifespan setup exactly
**Context:** httpx `ASGITransport` does not trigger FastAPI lifespan events. Phase 5 hit `KeyError: 'crm_client'` three separate times across three different test fixtures (conftest, CRM failures, CRM integration) because `app.state.crm_client` was only created in the lifespan, not in the fixture.
**Decision:** Every ASGI test fixture must manually create ALL `app.state` attributes that the lifespan creates: `engine`, `session_factory`, and every cross-service client (`crm_client`, future `catalog_client`, `payment_client`). A test fixture that omits any attribute the lifespan sets will fail at request time, not at fixture setup — making the error non-obvious.
**Alternatives:** (a) Run lifespan in tests — `ASGITransport` doesn't support it. (b) Extract lifespan setup into a shared function called by both lifespan and fixtures — viable but adds indirection for a pattern that's fixture-local.
**Consequences:** Every service's conftest.py and any standalone test fixtures (integration, failure simulation) are responsible for complete `app.state` setup. When a service adds a new cross-service client, every fixture must be updated. This is a known maintenance cost accepted in exchange for the simplicity of the ASGI test transport approach.

### 2026-04-12 — Phase 6 — Subscription state machine

| From | Trigger | To | Guard | Action |
|---|---|---|---|---|
| pending | activate | active | payment.charge succeeds | init_balance, set activated_at, set period_start/end, set next_renewal_at, emit `subscription.activated` |
| pending | fail_activate | terminated | payment.charge fails | release_msisdn (InventoryClient), release_esim (InventoryClient), set terminated_at, emit `subscription.terminated` |
| active | exhaust | blocked | primary allowance (data) remaining <= 0 | emit `subscription.exhausted`, emit `subscription.blocked` |
| blocked | top_up | active | vas payment succeeds | add_allowance, record VasPurchase, emit `subscription.vas_purchased`, emit `subscription.unblocked` |
| active | top_up | active | vas payment succeeds | add_allowance, record VasPurchase, emit `subscription.vas_purchased` |
| active | renew | active | renewal payment succeeds | reset_balance to plan defaults, advance period, set next_renewal_at, emit `subscription.renewed` |
| active | renew_fail | blocked | renewal payment fails | emit `subscription.renew_failed`, emit `subscription.blocked` |
| active | terminate | terminated | — | release_msisdn, recycle_esim, cancel pending VAS, set terminated_at, emit `subscription.terminated` |
| blocked | terminate | terminated | — | release_msisdn, recycle_esim, cancel pending VAS, set terminated_at, emit `subscription.terminated` |

Terminal states: `terminated`.

Forbidden transitions: any trigger from `terminated`, any undefined `(from_state, trigger)` pair → PolicyViolation.

### 2026-04-12 — Phase 6 — Test endpoint `consume-for-test` is temporary scaffolding
**Context:** Phase 6 needs a way to simulate rated usage arriving before the real `usage.rated` event consumer exists (Phase 8).
**Decision:** `POST /subscription/{id}/consume-for-test` simulates balance decrement. Gated by `BSS_ENABLE_TEST_ENDPOINTS=true` env var. The router is not registered when the flag is false.
**Alternatives:** Build the real event consumer early — too much Phase 8 scope creep.
**Consequences:** **This endpoint must be removed in Phase 8** when the real `usage.rated` event consumer replaces it. If it ships to v0.1 without a gate, usage simulation can bypass Mediation's ingress rules and break the block-on-exhaust doctrine.

### 2026-04-12 — Phase 7 — COM order state machine

| From | Trigger | To | Guard | Action |
|---|---|---|---|---|
| acknowledged | start | in_progress | — | emit `order.in_progress` |
| acknowledged | cancel | cancelled | — | emit `order.cancelled` |
| in_progress | cancel | cancelled | no service_order exists (SOMClient check) | emit `order.cancelled` |
| in_progress | complete | completed | triggered by `service_order.completed` event | call SubscriptionClient.create, emit `order.completed` |
| in_progress | fail | failed | triggered by `service_order.failed` event | emit `order.failed` |

Terminal states: `completed`, `failed`, `cancelled`.

Notes: `acknowledged → in_progress` happens synchronously within POST /productOrder. SOM cleanup releases resources before emitting `service_order.failed`, so COM does not call InventoryClient on failure.

### 2026-04-12 — Phase 7 — SOM ServiceOrder state machine

| From | Trigger | To | Guard | Action |
|---|---|---|---|---|
| acknowledged | start | in_progress | — | decompose, reserve resources, create services, emit provisioning tasks |
| in_progress | complete | completed | all services activated | emit `service_order.completed` with CFS characteristics |
| in_progress | fail | failed | any service permanently failed | release MSISDN + eSIM via InventoryClient, emit `service_order.failed` |

Terminal states: `completed`, `failed`.

### 2026-04-12 — Phase 7 — SOM Service state machine (CFS + RFS)

| From | Trigger | To | Guard | Action |
|---|---|---|---|---|
| designed | reserve | reserved | — | CFS: reserve MSISDN+eSIM via InventoryClient, populate characteristics; RFS: mark provisioning tasks submitted |
| reserved | activate | activated | RFS: all tasks completed; CFS: all child RFS activated + all CFS tasks completed | emit `service.activated` |
| designed | fail | failed | — | — |
| reserved | fail | failed | — | CFS: release MSISDN+eSIM via InventoryClient |
| activated | terminate | terminated | — | CFS: release MSISDN, recycle eSIM |

Terminal states: `failed`, `terminated`.

Notes: `feasibility_checked` state exists in the model but is skipped in v0.1. Services are created directly in `designed`. Task completion tracked in service `characteristics` JSONB via `pending_tasks` dict.

### 2026-04-12 — Phase 7 — RabbitMQ pub/sub introduced
**Context:** Existing publisher only writes to `audit.domain_event` with `published_to_mq=False`. Phase 7 requires event consumers (SOM listens for `order.in_progress`, `provisioning.task.completed`; COM listens for `service_order.completed`; provisioning-sim listens for `provisioning.task.created`).
**Decision:** Enhance publisher to accept an optional `aio_pika.Exchange` parameter. After writing the audit row and committing, publish to RabbitMQ best-effort. Each consuming service declares its own durable queue bound to `bss.events` topic exchange during lifespan startup. Existing services (catalog, crm, payment, subscription) that don't consume events pass `exchange=None` and continue audit-only.
**Alternatives:** (a) Separate outbox worker polling `published_to_mq=False` rows — more reliable but adds infrastructure complexity for v0.1. (b) Publish before commit — risks publishing events for rolled-back transactions.
**Consequences:** First real event-driven flow in the system. Consumers must be idempotent. Replay job (post-v0.1) can republish from audit rows where `published_to_mq=False`.

### 2026-04-12 — Phase 7 — eSIM release vs recycle distinction
**Context:** Failure cleanup requires returning a reserved eSIM to `available`. Existing `recycle_esim` transitions `activated→recycled`, not `reserved→available`.
**Decision:** Add `POST /inventory-api/v1/esim/{iccid}/release` endpoint to CRM + `release_esim(iccid)` to InventoryClient. `release` = reserved→available (failed/cancelled order, eSIM never used). `recycle` = activated→recycled (terminated subscription, eSIM was used).
**Alternatives:** Overload `recycle` to handle both — breaks the eSIM state machine semantics.
**Consequences:** SOM calls `release_esim` on failure, `recycle_esim` on termination. Phase 6 subscription code uses `recycle_esim` on fail_activate path — acceptable for now since the subscription is being terminated, but could be tightened to `release_esim` in a future cleanup.

### 2026-04-11 — Phase 5 — Integration tests must use unique identifiers per run
**Context:** `test_payment_crm_integration.py` hardcoded `integ-payment@test.com` as the test customer email. On second run, CRM returned 422 (`email_unique` policy), test silently skipped with "Could not create test customer: 422". This made it look like CRM was down when it was actually working.
**Decision:** Integration tests that create real data in external services must use `uuid.uuid4().hex[:8]` or similar in any unique field (email, MSISDN, external refs). The test should still clean up after itself where possible, but uniqueness prevents silent failures on re-run.
**Alternatives:** Clean up test data in teardown — fragile if test crashes mid-run; doesn't help if previous run's teardown failed.
**Consequences:** Integration tests are idempotent across runs. Silent skips from unique-constraint violations are eliminated.

### 2026-04-12 — Phase 8 — Mediation is TMF635 online mediation, not OCS, not batch
**Context:** "Mediation" is overloaded in telco. Three distinct things share the name: (1) batch mediation — offline CDR collection, deduplication, enrichment against RAN probe files (Amdocs, Nokia NetAct territory); (2) OCS — Online Charging System, real-time authorization/reservation/grant of quota per 3GPP Gy, typically built on Diameter; (3) TMF635 online mediation — accepts parsed usage events via API and forwards to downstream systems for rating/charging.
**Decision:** BSS-CLI implements (3). `services/mediation/` exposes `POST /usage` accepting already-parsed events (subscription_id, event_type, quantity), validates against a blocked-subscription guard, persists to `mediation.usage_event`, and publishes `usage.recorded`. It does NOT collect CDRs from network probes (out of scope, channel/RAN concern) and does NOT perform real-time Gy credit control (no quota reservation — we are bundled-prepaid with block-on-exhaust, not OCS).
**Alternatives:** (a) Build an OCS-shaped pre-authorization layer — contradicts doctrine #3 (block-on-exhaust, not reservation). (b) Skip mediation and have Rating consume usage directly — loses the block-at-edge guard and the clean TMF635 surface.
**Consequences:** Mediation's job is narrow: receive, validate, forward. Rating consumes `usage.recorded`, computes allowance consumption, publishes `usage.rated`. Subscription consumes `usage.rated`, decrements balance, blocks on exhaust. Three clean planes with clear responsibilities.

### 2026-04-12 — Phase 8 — Concurrent decrement: SELECT FOR UPDATE per balance row
**Context:** Subscription's `usage.rated` consumer decrements `bundle_balance.remaining` under concurrent load. With `prefetch_count=5` on the MQ consumer and multiple rated events arriving for the same subscription+allowance, naive read-modify-write loses updates. Must guarantee that N concurrent decrements of quantity Q_i produce a final balance of `max(0, initial - sum(Q_i))` with at most one exhaust transition.
**Decision:** Option A — pessimistic locking via `SELECT ... FOR UPDATE` on the `bundle_balance` row. `SubscriptionRepository.get_balance_for_update(sub_id, allowance_type)` uses SQLAlchemy's `.with_for_update()`; each event gets its own session, and the row lock serializes concurrent handlers for the same (subscription, allowance) tuple. Different allowances or different subscriptions remain parallel.
**Alternatives:** (b) Optimistic concurrency with a `version` column and retry-on-conflict — requires schema change, retry logic in the consumer, and still needs a backoff bound; under bursty load the retry storms defeat the purpose. (c) MQ partitioning by subscription_id — requires consistent-hash exchange or per-subscription queues, operationally heavier, and doesn't help cross-allowance coordination if we ever add one.
**Consequences:** Correct under contention, simple to reason about. Lock scope is one row per allowance so fan-out parallelism is preserved across the subscriber base. Lock is held only for the duration of the decrement + exhaust transition (a handful of statements); if that window grows, revisit.

### 2026-04-12 — Phase 8 — Phase 6 `consume-for-test` endpoint removed, not gated
**Context:** Phase 6 introduced `POST /subscriptions/{id}/consume-for-test` as a stand-in for real usage, used by tests to drive exhaustion. Phase 8 replaces it with the real `usage.rated` consumer path. Two options: gate the test endpoint behind `BSS_ENABLE_TEST_ENDPOINTS`, or delete it entirely.
**Decision:** Delete. The endpoint, its schema, its router registration, and the `enable_test_endpoints` config flag are all removed. Tests that previously POSTed to the endpoint now use a `simulate_usage` pytest fixture that calls `SubscriptionService.handle_usage_rated` directly with the rolled-back transactional session — exercising the real production code path.
**Alternatives:** Gate behind env flag — leaves dead code paths in prod images, tempts future re-use, and the fixture approach actually exercises more of the real code (the consumer handler) than an HTTP test endpoint would have.
**Consequences:** No test-only endpoints in prod surface. Subscription's public API is purely customer lifecycle + VAS. The decrement path is exercised identically in tests and production.

### 2026-04-12 — Phase 10 — Scenario runner is its own YAML dialect, not pytest
**Context:** Phase 10 needs end-to-end flows (signup → exhaustion → recovery) that a human can read and an LLM can extend. Options: (a) pytest-style integration tests, (b) bash scripts against the CLI, (c) a dedicated YAML DSL with `action:` / `assert:` / `ask:` steps.
**Decision:** (c). Scenarios live in `scenarios/*.yaml` and are parsed by pydantic into `Scenario(setup, steps[], teardown)`. Steps are a tagged union: `action:` (fire a tool, optionally `capture:` into context), `assert:` (poll a tool until `expect:` matches or times out), `ask:` (hand the natural-language prompt to the LangGraph supervisor). The runner is a straight walk — no conditionals, no retries, no branching.
**Alternatives:** pytest parametrize — loses the "readable by a non-engineer" property that makes scenarios good onboarding material, and couples scenarios to a test framework we don't want the scenario runner to depend on. Bash — no structured assertions, no JSONPath captures, no polling primitive, no LLM hook.
**Consequences:** Scenarios are auditable artifacts (not code). The same YAML is the demo script, the regression suite entry, and the LLM eval harness. A `forced:` mode (Phase 11) can rewrite every `action:` into a natural-language instruction and run it through the LLM — the same YAML doubles as an LLM-capability benchmark.

### 2026-04-12 — Phase 10 — Scenario runner owns `admin.reset_operational_data` and `clock.*`
**Context:** `TOOL_REGISTRY` has `admin.reset_operational_data` and `clock.freeze` / `unfreeze` / `advance` entries, but those are NOT_IMPLEMENTED stubs — they exist so the LLM has a surface it can mention, not so it can actually drive them. The scenario runner needs real fan-out: reset hits every service, freeze sets every service's clock to the same instant.
**Decision:** `_SCENARIO_ACTIONS` dict in `cli/bss_cli/scenarios/actions.py` shadows the registry for these four names. `resolve_action(name)` checks the shadow dict first, then `TOOL_REGISTRY`. Scenario YAML can call them as `action: admin.reset_operational_data` without the LLM ever being able to. The real callables live in `packages/bss-admin/` and `packages/bss-clock/`.
**Alternatives:** Let the LLM call them — violates the "destructive operations gated" rule even with `--allow-destructive`, because these aren't single-resource destructive; they're global. Have the scenario runner call the admin CLI via subprocess — loses error typing and makes tests slow.
**Consequences:** Clear separation: the LLM operates on customer-scoped tools; the scenario runner operates on the global test harness. If a future tool needs both surfaces, add it to both — but start with scenario-only and promote only if needed.

### 2026-04-12 — Phase 10 — `_LLM_HIDDEN_TOOLS` filter vs. removing from TOOL_REGISTRY
**Context:** `usage.simulate` is a genuine write tool — it submits a CDR to mediation that decrements a real balance. Hero scenarios 1 and 2 need it (via `action:`) to drive exhaustion. Hero scenario 3 (LLM ship gate) showed MiMo v2 Flash using it as a verify-the-fix step: after purchasing a VAS, the model would simulate usage to "confirm data works", re-exhaust the bundle, loop to recursion_limit, and fail. Dropping `usage.simulate` from `TOOL_REGISTRY` entirely breaks scenarios 1 and 2.
**Decision:** Keep `usage.simulate` in the registry (so `action:` steps can call it) but filter it out of `build_tools()` via `_LLM_HIDDEN_TOOLS` — a frozenset in `graph.py`. The LLM sees 75 tools; scenarios see 76. A test asserts the filtered list size matches `len(TOOL_REGISTRY) - len(_LLM_HIDDEN_TOOLS)` so silent drift is caught.
**Alternatives:** (a) Delete from registry — breaks scenarios 1/2 and forces every test-harness usage-injection to go through raw HTTP to mediation. (b) Stronger prompt ("NEVER call usage.simulate") — small models ignore negative instructions under pressure; observed empirically on three runs before the filter landed. (c) Per-call gate that rejects LLM-channel calls — requires plumbing channel into every tool, and fails open if the plumbing breaks.
**Consequences:** `_LLM_HIDDEN_TOOLS` is the hook for future "scenario-only" surfaces (e.g. clock.advance when we add it as a live tool). It sits next to `DESTRUCTIVE_TOOLS` in spirit — a per-tool safety list the human reviews. If an LLM genuinely needs to simulate usage (future agent-driven load testing?), add a separate `usage.simulate_for_test` tool with a noisier name, not re-exposure.

### 2026-04-12 — Phase 10 — Tool exceptions wrap-in-coroutine, not `handle_tool_error`
**Context:** LangChain's `StructuredTool.handle_tool_error=<callable>` is documented as "convert tool errors to observations". Empirically it only catches `ToolException`; `httpx.HTTPError`, our `ClientError`, and `PolicyViolationFromServer` propagate out of `graph.ainvoke` and crash the scenario. Observed on hero scenario 3 where a 404 from a fabricated subscription ID tore down the graph.
**Decision:** In `graph._as_structured_tool`, wrap the already-gated coroutine in a `try/except Exception` that returns `_tool_error_to_observation(exc)` — a JSON-shaped string. The `StructuredTool` now always "succeeds" from LangGraph's perspective; the LLM reads the error observation and decides what to do. `functools.wraps(fn)` preserves the original signature so `infer_schema` still produces the correct JSON Schema for the LLM.
**Alternatives:** (a) Raise `ToolException(str(exc))` inside the except — loses the structured fields (`rule`, `status_code`) the LLM can reason about. (b) Use LangGraph's error-handling node — extra graph state to thread, and still requires exception → observation conversion somewhere.
**Consequences:** Every tool is crash-proof at the graph boundary. The conversion is one function with explicit `isinstance` branches for each error type — new error types need a branch. Tool callers can still raise; they just won't blow up the ReAct loop. The scenario runner's `expect_tools_called_include` counts tools by `ToolMessage.name`, which only fires on successful return — so converted errors still show up in the trace as "tool X was called" (correct, since the call happened; the model just read an error back).

### 2026-04-12 — Phase 10 — Interaction log `channel=llm` is the v0.1 ship-gate audit signal
**Context:** Hero scenario 3 asserts "the LLM's actions are audit-visible on the customer record". Two candidate signals: (a) the TMF683 interaction log — server-side `channel` column, captured from the `X-BSS-Channel` header; (b) the `audit.domain_event` table — has a richer `actor` field (`llm-<model-slug>`) plus every state transition. The TMF683 `Interaction` row model has no `actor` column in v0.1.
**Decision:** Assert `channel=llm` on `interaction.list` as the ship gate. Adding an `actor` column to `crm.interaction` requires a migration and cross-service back-population, which is Phase 11 scope. `audit.domain_event` already captures actor — the richer "which model did what" forensic view is available via the audit API for anyone who needs it.
**Alternatives:** (a) Add `actor` to Interaction now — schema churn for a property already captured elsewhere. (b) Query `audit.domain_event` in the scenario — works but couples the ship gate to a schema that's still in flux (Phase 9 just finished wiring it) and makes the assertion less readable.
**Consequences:** TMF683 stays the CSR-facing "what happened on this account" view, audit.domain_event stays the "forensic append-log" view. v0.1 ships with the two-layer model intact. If a future requirement is "a CSR can see which model answered the customer's question", add `actor` to Interaction then; don't do it speculatively.

### 2026-04-12 — Phase 10 — Ship-gate scenarios are structured as deterministic-setup → LLM-step → deterministic-verification
**Context:** An LLM scenario can fail for two reasons: the stack is broken (determinism bug) or the model is flaky (LLM regression). Mixing the two into one pass/fail number makes triage awful.
**Decision:** Hero scenario 3 (and all future ship-gate LLM scenarios) is a three-phase structure: (1) deterministic setup — drive the stack into a known state via `action:` steps that bypass the LLM entirely; (2) single `ask:` step that hands the problem to the LLM; (3) deterministic verification — `assert:` steps that query the final state directly, NOT via the LLM's self-report. If phase (1) fails the stack is broken. If phase (3) fails the LLM didn't fix the thing, regardless of what it claims in its final message.
**Alternatives:** Let the LLM drive everything — the setup becomes a correctness gate for the LLM's ability to drive happy-path flows, which is a separate test. Accept the LLM's self-report — models lie by omission when they run out of recursion; a confident "I fixed it" doesn't mean they did.
**Consequences:** Three runs in a row pass before a release. If the stack is stable but run 1 fails, it's the model — rerun, or bump model/temperature. If all three fail identically at the same determinism step, it's the stack — investigate. Clear signal, fast triage.

### 2026-04-13 — v0.1.1 — Billing service deferred to v0.2

**Context:** Phase 0 planned a billing service as service #9 of 10 (TMF678,
port 8009, `billing` schema with `billing_account` and `customer_bill` tables).
The Phase 2 initial migration created the schema and tables. No phase 1-10
implemented the service layer — the orchestrator shipped with NOT_IMPLEMENTED
stub tools (`billing.get_account`, `billing.list_bills`, `billing.get_bill`,
`billing.get_current_period`), an empty `services/billing/` directory with
only a pyproject.toml, a `BillingClient` stub in bss-clients, and a running
but functionally empty container. v0.1.0 shipped with this drift.

**Decision:** Formally defer billing to v0.2 as a read-only view layer over
`payment.payment_attempt`. Clean up v0.1.0 drift in v0.1.1: delete the
orchestrator stubs, delete the bss-clients billing module, delete the
empty services/billing/ directory, remove the container from docker-compose,
preserve the migration and ORM models so v0.2 work is purely additive.

**Alternatives:**
- (A) Drop billing entirely from the v0.2 roadmap too — rejected because
  TMF678 Customer Bill Management is core TMF surface and worth having
  in v0.2 for credibility.
- (B) Build minimal billing as v0.1.1 — rejected as scope creep on a
  cleanup release. A billing service deserves its own phase budget with
  proper scoping, policies, tests, and scenario coverage.
- (C) Defer to v0.2 as a read-only view layer over payment.payment_attempt
  — selected. Bundled prepaid doesn't generate formal invoices (charges
  happen at activation/renewal/VAS purchase, recorded in payment.payment_attempt),
  so v0.2 billing becomes a receipt aggregation and statement generation
  layer rather than a full invoice/dunning/credit pipeline.

**Consequences:**
- v0.1 service count: 9, not 10. ARCHITECTURE.md, CLAUDE.md, README.md
  updated accordingly.
- The `billing` schema and its tables remain in Postgres from Phase 2
  migrations. They are empty and dormant in v0.1. v0.2 will populate
  them as a view layer.
- `packages/bss-models/bss_models/billing.py` (ORM models) is preserved
  because it mirrors the migration.
- `packages/bss-clients/bss_clients/billing.py` (HTTP client stub),
  `orchestrator/bss_orchestrator/tools/billing.py` (tool stubs), and
  `services/billing/` (empty service directory) are deleted.
- Port 8009 is reserved for v0.2 billing; docker-compose.yml has a
  comment marking it as such.
- v0.2 billing work is purely additive: build the service, implement
  policies, wire endpoints — no schema work needed.

**Important scope note — "billing" as CRM vocabulary is preserved.**
CRM services (`services/crm/app/services/ticket.py`, `case.py`,
`types.py`) reference "billing" as a customer-support category and
ticket type (`billing_dispute`, `billing_issue`, `category="billing"`).
This is CRM domain vocabulary, not billing-service coupling. Real
telcos classify customer complaints as "billing issues" whether or
not there is a dedicated billing microservice. These references remain
unchanged in v0.1.1 and should not be targeted in any future cleanup.
The cleanup rule is: remove references to the billing **service**
(tools, clients, endpoints, docker-compose entries, ports), never
remove billing as customer-support **vocabulary** in other domains.

### 2026-04-23 — v0.2.0 — Jaeger all-in-one as the trace backend (not Tempo)
**Context:** OTel exports need a backend. Two viable choices: Jaeger
(mature, simpler) and Tempo (newer, cloud-native, object-storage-backed).
**Decision:** Jaeger all-in-one (`jaegertracing/all-in-one:1.65.0`).
Single container, no object-storage dependency, built-in UI on `:16686`,
native OTLP/HTTP (`:4318`) and OTLP/gRPC (`:4317`) ingress via
`COLLECTOR_OTLP_ENABLED=true`. ~200 MB RAM. The `bss trace` CLI reads
via Jaeger's stable HTTP JSON API (`/api/traces/<id>`).
**Alternatives rejected:** Tempo — needs S3/MinIO/filesystem storage,
Grafana for the UI, and per-deployment credentials. v0.2 is "ship a
screenshot", not "operate a production observability stack".
**Consequences:** Memory storage by default, lost on restart — fine
for demo. Persistence via badger volume documented in
`docs/runbooks/jaeger-byoi.md` for long-running BYOI hosts. If
production scale ever lands here, migration to a storage-backed
trace tier is independent of how services emit (services just point
at a different OTLP endpoint).

### 2026-04-23 — v0.2.0 — FastAPI middleware-stack cache invalidation after instrument_app
**Context:** Smoke-testing v0.2 found events written from FastAPI HTTP
handlers (`payment.charged`, `customer.created`, `order.acknowledged`)
had NULL `trace_id` in `audit.domain_event`, even though events from
MQ consumers and from inside manual spans had trace_ids. Confirmed
via Jaeger: no FastAPI server spans for any HTTP request — only
auto-instrumented SQL spans showed up as orphaned root spans.
**Root cause:** Starlette caches `app.middleware_stack` on the FIRST
`app.__call__`. The very first call IS the lifespan invocation. By the
time `configure_telemetry(service_name=..., app=app)` runs in lifespan
startup, the stack is already built (without OTel). All subsequent
real requests use the cached, un-instrumented stack.
**Decision:** After `FastAPIInstrumentor.instrument_app(app)`, set
`app.middleware_stack = None` to force a rebuild on the next request.
The rebuild picks up the OTel-patched `build_middleware_stack` and
the server span wraps every request properly.
**Alternatives rejected:** Move `configure_telemetry` to import time
before `app = FastAPI(...)` — splits config across import vs. lifespan,
surfaces the env-vars-not-yet-loaded race. Subclass FastAPI to
invalidate on `instrument_app` — same effect, more indirection.
**Consequences:** One extra line in `bss_telemetry.bootstrap`. trace_id
coverage on `audit.domain_event` jumped from ~50% to ~95% after this
fix. Documented in `bootstrap.py` with the full why so future readers
don't accidentally drop the line during refactors.

### 2026-04-23 — v0.2.0 — RequestIdMiddleware rewritten as pure ASGI (was BaseHTTPMiddleware)
**Context:** While diagnosing the trace_id-NULL bug above, the first
hypothesis was Starlette's `BaseHTTPMiddleware` running the inner app
in a separate asyncio task and breaking ContextVar propagation
(documented OTel + Starlette interaction issue). My
`RequestIdMiddleware` in all 9 services extended `BaseHTTPMiddleware`.
The cache fix above turned out to be the actual root cause, but the
ASGI rewrite landed as defense-in-depth and removes a known fragility.
**Decision:** Rewrite each service's `RequestIdMiddleware` as pure ASGI
(callable taking `scope, receive, send`). Same behavior — extract
context headers, populate auth_context + structlog contextvars,
inject `x-request-id` on response, catch PolicyViolation /
ServerError / RatingError into structured 422/500 JSON responses.
Per-service quirks preserved: rating handles `RatingError` not
`PolicyViolation`; catalog has no exception handling.
**Alternatives rejected:** Keep `BaseHTTPMiddleware` and rely on the
cache fix alone — works in current OTel, but `BaseHTTPMiddleware` is
documented as fragile around contextvars. Extract a shared
`RequestIdMiddleware` into `bss-middleware` — the right shape, but
v0.3 spec already creates `packages/bss-middleware/` for the API
token middleware; v0.3 will collapse the duplication.
**Consequences:** Nine `services/*/app/middleware.py` files rewritten,
~80 lines each. All v0.1 hero scenarios still pass. v0.3 will
consolidate into a shared package.

### 2026-04-23 — v0.2.0 — /health excluded from FastAPI auto-instrumentation
**Context:** Docker `HEALTHCHECK --interval=10s` hits each service's
`/health` six times a minute. Without exclusion, the Jaeger UI's
"most recent traces" view for any service is 99% healthcheck noise
and the actual business activity is buried.
**Decision:** Pass `excluded_urls="/health,/health/.*,/metrics"` to
both `FastAPIInstrumentor.instrument_app(app)` and the global
`FastAPIInstrumentor().instrument()` paths. OTel's `parse_excluded_urls`
splits on comma and `re.search`-matches each pattern against the full
request URL.
**Consequences:** Jaeger UI is immediately useful — pick `bss-com` and
the recent trace is the actual signup, not the last six healthchecks.
`/metrics` excluded preemptively for a possible Prometheus scrape later.

### 2026-04-23 — v0.2.0 — Step 2 of the spec was a no-op: aio-pika auto-instrumentation handles consume
**Context:** The v0.2.0 spec called out a Step 2 task to add a consumer
wrapper in `bss-events` so MQ consumers activated the upstream
traceparent context for span propagation across the MQ boundary.
The `bss_telemetry.use_amqp_span` helper was written for this purpose.
**Discovery:** Reading the OTel `aio-pika` instrumentor source revealed
that `Queue.consume` is patched at instrument time so the consumer
callback is wrapped in a `CallbackDecorator` that handles context
extraction + span creation automatically. No manual wrapping needed.
**Decision:** Skip the Step 2 wrapping entirely. `use_amqp_span` stays
in `bss_telemetry.propagation` as a typed escape hatch for any future
case where auto-instrumentation isn't enough, but isn't called from
anywhere in v0.2.
**Verification:** Smoke test confirmed cross-service traces span the
MQ boundary cleanly: a signup produced one trace covering com → MQ →
som → MQ → provisioning-sim (×4 parallel) → MQ → som → MQ → com →
subscription. 125 spans, 8 services, single trace_id throughout.
**Consequences:** `bss-events` package didn't actually have any
consumer code (consumer code lives per-service in
`services/<svc>/app/events/consumer.py`); my spec was wrong about
where the wrapping would have lived.

### 2026-04-23 — v0.2.0 — Trace tools return summaries, not raw Jaeger payloads
**Context:** `trace.get` / `trace.for_order` / `trace.for_subscription`
are in TOOL_REGISTRY (LLM-callable). Jaeger returns the full trace
JSON which is 8000+ lines for a 125-span signup trace. Putting that
in the LLM context every call would burn tokens and degrade reasoning.
**Decision:** Tools return a summary dict — `{traceId, spanCount,
serviceCount, services, errorSpanCount, totalMs}` plus an aggregate-id
field on the `for-*` variants. Humans wanting the full swimlane use
the `bss trace get <id>` CLI command (which fetches the full Jaeger
payload and renders ASCII via `cli/bss_cli/renderers/trace.py`).
**Consequences:** LLM's `trace.for_order` response is ~150 bytes
instead of ~250 KB. Human inspection is one extra command (CLI
swimlane) but gives the better presentation.

### 2026-04-23 — v0.3.0 — Shared API token over OAuth for single-operator auth
**Context:** v0.1 and v0.2 ship without authentication. The moment the
stack is reachable from anything beyond `localhost` or a private VPN,
every BSS service is a credential-free admin API surface. Phase 12
ships proper OAuth2 + per-principal RBAC, but that's two weeks of
work; we needed a two-hour fix that closed the open-door problem
without prejudicing the Phase 12 design.
**Decision:** A single shared admin token (`BSS_API_TOKEN`) gates
every BSS service. New `packages/bss-middleware/` ships
`BSSApiTokenMiddleware` (pure ASGI, timing-safe `hmac.compare_digest`,
exempts only `/health`, `/health/ready`, `/health/live`).
`bss-clients` gets `TokenAuthProvider` alongside the existing
`NoAuthProvider`. Services validate the token at lifespan startup
(`validate_api_token_present()`) — empty / `"changeme"` / <32-char
tokens fail-fast.
**Alternatives rejected:**
- (a) **OAuth2 client credentials** — multi-week build (auth service,
  client registration, JWT signing/verification, key rotation, scope
  catalog). Not justified for single-operator scale; deferred to
  Phase 12 in full.
- (b) **mTLS between services** — cert lifecycle complexity
  (generation, rotation, revocation, distribution) for the same
  authentication outcome.
- (c) **IP allowlisting at infra layer** — fragile (containers move,
  IPs change, dev-vs-prod split), provides no defense once an
  attacker is on the network.
- (d) **Per-endpoint `Depends(require_token)`** — middleware is the
  chokepoint by construction; per-endpoint decoration is what you
  do when you want some endpoints unprotected, and we don't.
**Consequences:**
- Phase 12 upgrade path is one swap: replace `BSSApiTokenMiddleware`
  with a JWT-validating middleware, replace `TokenAuthProvider`'s
  static token with a JWT issuer. `auth_context.py` reads claims
  from the JWT instead of headers. Policy code, business logic,
  and the entire bss-clients caller surface are untouched.
- `auth_context.py` per-service is left ALONE in v0.3 — the spec
  said to refactor it but the existing implementation already
  populated from a ContextVar via `RequestIdMiddleware`. v0.3's
  middleware just gates whether that path runs at all.
- The middleware ships as **pure ASGI** (not BaseHTTPMiddleware),
  avoiding the contextvar-task-spawn fragility we hit in v0.2.
- Rotation is restart-based, ~60s downtime
  (`docs/runbooks/api-token-rotation.md`). Zero-downtime rotation
  is a real auth-system feature, deferred to Phase 12.
- Per-service `RequestIdMiddleware` is duplicated across 9 services
  (consequence of v0.2's pure-ASGI rewrite). v0.3 spec called for
  consolidation into `bss-middleware` but kept the duplication for
  scope discipline. Future refactor.

### 2026-04-23 — v0.3.0 — Step 2 of the v0.3 spec was a no-op (auth_context unchanged)
**Context:** The v0.3 spec said: "every service has `app/auth_context.py`
that today returns a hardcoded admin principal regardless of request
state. In v0.3, the middleware writes to a `ContextVar` on successful
token validation, and `auth_context.current()` reads from it."
**Discovery during reconnaissance:** The auth_context module ALREADY
reads from a `ContextVar`. `RequestIdMiddleware` (existing since
Phase 5) populates it via `set_for_request(actor, tenant, channel)`
from the `X-BSS-Actor` / `X-BSS-Channel` / `X-BSS-Tenant` request
headers. The "hardcoded admin principal" claim in the spec was
wrong — it's the ContextVar's *default* that's the admin principal,
overridable per-request.
**Decision:** Skip the planned auth_context refactor. The existing
ContextVar-based design works as-is. v0.3 just adds gating in front
of it (the middleware) without touching the principal-population
path.
**Consequences:** ~9 fewer files touched. No risk of subtle
behavior shift in audit/interaction logging. The "actor" in audit
events still comes from the `X-BSS-Actor` header (still trusted, as
v0.3 is single-tenant-shared-token scope; Phase 12 takes that from
JWT claims).

## 2026-04-23 — v0.4.0 — Portal writes route through the LLM orchestrator
**Context:** A web portal needs a write path. The natural instinct is
to have route handlers call `bss-clients` mutating methods directly —
it's one hop, it's fast, it's familiar. The alternative is to translate
every portal write into a natural-language instruction and run it
through the LangGraph ReAct agent (`bss_orchestrator.session.astream_once`).
**Decision:** Every portal write goes through the agent. Route handlers
never import `CustomerClient.create`, `OrderClient.create`, etc. Reads
(list offerings, fetch subscription, poll order state) still go direct
— LLM-mediating a pass-through read is pointless latency.
**Alternatives:** (a) Direct bss-clients writes from handlers —
rejected; creates a second write path that drifts from the CLI over
time, and the "every write goes through the policy layer via the
agent or CLI" claim in CLAUDE.md becomes a lie. (b) Portal drives a
custom thin agent without LangGraph — rejected; duplicates the tool
dispatch logic.
**Consequences:** Portal writes are policy-gated through the same
chokepoint as CLI writes. The agent log widget — streamed via SSE
in real time — becomes the v0.4 demo artifact: the viewer watches
the LLM chain `customer.create → attest_kyc → add_card → order.create
→ wait_until → get_esim_activation` while the form submits. Latency
cost: ~10-20s per signup on MiMo v2 Flash, up to 60s on a worse
model. For a demo, that's the point; for a real customer portal it
would be unacceptable and Phase 12+ would add a direct write path
gated by `auth_context.role`.

## 2026-04-23 — v0.4.0 — Agent log widget streams HTML partials, not JSON
**Context:** The SSE stream from `/agent/events/{session}` needs a
frame format. JSON-with-client-side-templating is the obvious choice
— but that means shipping a template engine in the browser, which
means JS, which means a bundler.
**Decision:** Server-rendered HTML partials per SSE frame. HTMX's
`sse-swap` extension swaps each frame into a target element with no
JS on our side. One inline `<script>` block intercepts `htmx:sseMessage`
solely to chase the final `event: redirect` (navigates the whole
window when the agent signals "done").
**Alternatives:** JSON + React/Vue/Svelte — rejected; breaks the
"pure server-rendered, no bundler" rule. JSON + handwritten rendering
in vanilla JS — rejected; indistinguishable from adding a template
engine in 50 lines, and the HTML-partial path is strictly simpler.
**Consequences:** Zero client-side template logic. The widget is a
thin DOM shell; HTMX mutates it. The portal has exactly one JS file
we wrote (`static/js/agent_log.js` — 1 line of placeholder content
we haven't needed yet).

## 2026-04-23 — v0.4.0 — Portal skips inbound auth by design
**Context:** v0.3 ships `BSSApiTokenMiddleware` on every BSS service.
Consistency says put it on the portal too. But the portal is a public
signup surface — there's no token a prospect could send, and adding
one would make the demo not a demo.
**Decision:** No `BSSApiTokenMiddleware` on the portal. Its inbound
HTTP surface is fully open. Outbound calls to BSS services DO carry
`BSS_API_TOKEN` via the same `TokenAuthProvider` every other outbound
caller uses. Port 9001 should only be published where network-level
exposure control is acceptable (localhost, Tailscale, private VLAN).
**Alternatives:** A separate "portal token" header — rejected; no
real auth story, just security theater. Cloudflare Access / oauth2-proxy
in front — out of scope for a demo; deployers who need it can wire it
themselves.
**Consequences:** Anyone who can reach port 9001 can burn LLM budget
and create fake customers. That's deliberate for v0.x. Phase 12 swaps
this for customer-facing OAuth (Apple/Google Sign-In, SMS OTP) as a
first-class channel-layer concern.

## 2026-04-23 — v0.4.0 — KYC attestation uses per-customer signatures, no seed file
**Context:** Phase spec called for a `services/crm/bss_seed/kyc_prebaked.py`
seeding a known-good attestation token. Reconnaissance found the
existing `customer.attest_kyc` policy enforces a
`document_hash_unique_per_tenant` rule — one identity document =
one customer — so a single shared signature fails on the second
signup.
**Decision:** No seed file. The portal prompt derives the signature
per-customer by templating the email into
`myinfo-simulated-prebaked-v1::{email}`. The displayed attestation
ID (`KYC-PREBAKED-001`) stays stable so the UI reads consistently.
**Alternatives:** Pre-seed 100 known-good signatures and cycle through
them — rejected; non-deterministic across scenario runs. Bypass the
policy in dev mode — rejected; the policy chokepoint is the whole
point of Write Policy doctrine.
**Consequences:** The agent's `customer.attest_kyc` call passes the
uniqueness check every time. The attestation is still flagged
`not_verified` in CRM because the stub doesn't verify the signature
(there is no real Myinfo); downstream doesn't block on that, so the
subscription still activates. Real eKYC is a channel-layer concern
deferred indefinitely per CLAUDE.md §Scope boundaries.

## 2026-04-23 — v0.4.0 — Portal signup gets an MSISDN picker step (spec amendment)
**Context:** The v0.4 spec's signup flow was plan → form → agent.
Numbers were auto-assigned by SOM's `reserve_next_msisdn` during
decomposition. Manual testing surfaced the gap — a prospect expects
a "pick your number" moment, same as every real Singapore MVNO
signup (Singtel, Circles, M1, etc.).
**Decision:** Insert `GET /signup/{plan}/msisdn` between plan
selection and the form. The picker calls
`inventory.list_msisdns(state="available", limit=12)` and renders a
4×3 grid of tiles; each tile links to `/signup/{plan}?msisdn=...`.
The signup form now requires the query param and carries the number
as a hidden input through POST. `session.msisdn` stores it. The
agent prompt tells the LLM to pass `msisdn_preference=<number>` to
`order.create`, which COM already accepted and SOM already honored
via `reserve_next_msisdn(preference=...)`.
**Alternatives:** Defer to v0.5 — rejected; the demo felt broken
without it, and the plumbing was a one-line change on the agent
side (the tool already supported `msisdn_preference`). Lock-and-hold
the chosen number during session — rejected; demo-scale collisions
are harmless and the fallback-to-next-available behavior is the
right thing anyway.
**Consequences:** Spec widens from "one form, three fields" to
"picker + form". Hero scenario now captures the first available
MSISDN off the picker page (regex on `msisdn=([0-9]+)`), carries
it through the form, and asserts the subscription's `msisdn`
matches. DECISIONS entry is the amendment record — phases/V0_4_0.md
remains the original intent.

## 2026-04-23 — v0.4.0 — Scenario runner gains `http:` step type
**Context:** The portal hero scenario needs to drive the portal
through its public HTTP surface (landing → signup POST → SSE
trigger → status poll → confirmation). Existing step types are
`action:` (tool calls), `assert:` (read + match), `ask:` (LLM).
None can make an HTTP request.
**Decision:** Add an `http:` step type with GET/POST, form + json
bodies, expect matchers (status, body_contains, headers), the same
`poll:` contract as `assert:`, jsonpath `capture:` against a
synthetic `{status, headers, body, body_text}` shape, plus
`capture_regex:` for the common "pull a session id out of a
Location header" case, and `drain_stream:` to drive SSE endpoints
to completion.
**Alternatives:** Shell out to curl via a new `bash:` step —
rejected; YAML files would become opaque and non-portable. Drive
the portal through `action:` tool calls that themselves make HTTP
requests — rejected; the point of the portal hero is to exercise
the public HTTP surface, not bypass it.
**Consequences:** One new step type in schema.py + one handler in
http_step.py (~200 lines). The existing action/assert/ask path is
untouched. Future portals (v0.5 CSR console) reuse this step type
without extension.

## 2026-04-23 — v0.5.0 — Extracted `bss-portal-ui` shared package
**Context:** v0.4 put the agent log widget, SSE plumbing, base CSS,
and vendored HTMX inside `portals/self-serve/`. v0.5 needs them all
again for `portals/csr/`. Two paths: (a) copy-paste the templates +
helpers + assets into the new portal; (b) extract a shared package
*before* writing the second portal.
**Decision:** Extract `packages/bss-portal-ui/` as Step 1 of v0.5.
The package owns `partials/agent_log.html` + `partials/agent_event.html`,
the `project()` + `render_html()` event projection, the SSE frame
helpers (`format_frame`, `status_html`), the base CSS (palette,
layout primitives, agent log styling), and vendored HTMX. Each portal
loads templates via Jinja `ChoiceLoader` (portal-local first, then
shared fallback) and mounts the package's static at `/portal-ui/static/`.
Self-serve was refactored to consume the shared package as part of
the same v0.5 commit — no transitional state where one portal
duplicates and the other shares.
**Alternatives:** Copy-paste — rejected; guaranteed to drift the
moment one portal needs an agent-log fix the other doesn't get.
Extract after CSR is built — rejected; twice the work, twice the
merge conflicts. Keep agent_render in self-serve and have CSR import
it directly — rejected; couples the two portals at the source level
and breaks if self-serve is removed.
**Consequences:** Clean dependency graph (portals → bss-portal-ui →
bss-orchestrator for AgentEvent types). 51/51 self-serve tests still
pass after refactor; the v0.4 hero scenario still passes. Adding a
third portal in v0.6+ is mostly empty-shell scaffolding. Wheel build
needs a small `force-include` for the templates + static directories
so they ship inside the installed package.

## 2026-04-23 — v0.5.0 — Agent actions attributed to the operator, not the LLM, in interaction logs
**Context:** When a CSR types *"top up 5GB to their plan"* and the
LLM agent calls `subscription.purchase_vas`, what should the
`channel` and `actor` columns on the resulting `crm.interaction` row
say? Two natural choices: (a) `channel=llm, actor=llm-<model-slug>`
(matches the v0.1 pattern for CLI-driven `bss ask` calls); (b)
`channel=portal-csr, actor=<operator_id>` (matches *who asked*).
**Decision:** Option (b). The CSR portal sets `actor=<operator_id>`
on `astream_once(...)` so the orchestrator's `use_channel_context()`
populates the outbound `X-BSS-Actor` header with the human's id.
The interaction log answers *"who caused this to happen"*, and the
human is the cause; the LLM is the execution mechanism. Forensic
*"which model executed this"* still lives in `audit.domain_event.actor`
(`llm-<model-slug>`) — that's the right place for it.
**Alternatives:** `channel=llm` always — rejected; collapses two
distinct questions ("who asked" vs "what executed") into one column
and makes the CSR view less useful. A new column for the model —
rejected; `audit.domain_event` already has it, no need to duplicate.
**Consequences:** `astream_once` gains an `actor` parameter
(backwards compatible — defaults to `None`, preserving v0.4
self-serve behaviour). The v0.5 hero scenario asserts
`channel=portal-csr` on the interaction list. CSR view filters by
`actor=<op>` show what each operator did regardless of which model
ran their requests; LLM-comparison studies join `audit.domain_event`
on the same correlation id.

## 2026-04-23 — v0.5.0 — Stub login is NOT a security control
**Context:** The CSR portal needs an operator id on every outbound
call so the interaction log attributes agent-driven actions to a
human. Real auth (OAuth via Keycloak / Cognito / Entra) is a Phase 12
project. v0.5 needs *something* now to populate `X-BSS-Actor`.
**Decision:** Ship a stub login that accepts any credentials. POST
/login creates a UUID session token, stores `operator_id=<whatever
username was typed>` in the in-memory session store, and sets a
`bss_csr_session` cookie. Every authenticated route resolves the
cookie via a FastAPI dependency that 303s to /login if missing or
expired. The login is a **UX mechanism, not a lock** — it exists to
populate `X-BSS-Actor`, not to gate access.
**Alternatives:** No login at all — rejected; we need *some*
operator id. Hardcode `operator_id="csr-default"` — rejected; loses
multi-operator distinction in audit logs. Build real auth now —
out of scope for v0.5.
**Consequences:** Per V0_5_0.md §Security model, the CSR portal must
NOT be exposed beyond a trusted network (Tailscale / VPN / ops LAN).
Anyone who can reach port 9002 can act on any customer in the
database via the agent. The `BSS_API_TOKEN` (v0.3) is irrelevant
because the agent carries it on the attacker's behalf. Phase 12
swaps the stub login for OAuth + role-based tool gating; the
`auth_context` plumbing has been ready for it since v0.1.

## 2026-04-23 — v0.5.0 — CSR prompts inject customer + subscription snapshot
**Context:** A small model like MiMo v2 Flash given a bare CSR
question (*"why is their data not working?"*) without context
typically starts with `customer.list(name_contains="")` and tries
to rediscover state the operator already has on screen. That wastes
3-5 tool calls before the model lands on the right tree.
**Decision:** `agent_bridge.ask_about_customer` pre-fetches the
customer + subscription snapshots and injects them into the prompt
ahead of the operator's question. The prompt also includes
KNOWN_LEADS — three few-shot examples for the most common ask
patterns (blocked-subscription, top-up, open-ticket) — and a
constraint footer pinning the agent off destructive tools.
**Alternatives:** Bare prompt — rejected; small models drift.
Inject the entire customer 360 (cases, payment methods,
interactions) — rejected; payload bloat for marginal benefit;
the agent can call those tools when needed. RAG over a runbook
corpus — Phase 11 (`knowledge.search`); not v0.5.
**Consequences:** Agent reliably lands on `subscription.get_balance`
for data questions, `case.list` for ticket questions, etc.
The hero scenario passes 3 runs in a row at 12-17s each on MiMo
v2 Flash. Without the snapshot, the same model wandered for ~30s
and sometimes hit the timeout.

## 2026-04-23 — v0.6.0 — Catalog service granted formal layout exemption
**Context:** Every other v0.x service uses `services/<svc>/app/`
with subdirs (`api/`, `services/`, `policies/`, `repositories/`,
`domain/`, `events/`). Catalog uses a flatter pre-template layout
(`services/catalog/bss_catalog/{app.py, deps.py, repository.py,
routes/, schemas/}`). v0.6 set out to migrate it for consistency.
**Decision:** Formal exemption. Catalog stays on the
`bss_catalog/` package layout. Reasoning:
1. Catalog is read-only stateless — no policies, no service classes,
   no event publishers, no domain ORM models. Migrating to the
   standard template adds 4 empty directories (`services/`, `policies/`,
   `events/`, `domain/`) for symmetry's sake. Empty-directory ceremony
   was rejected per the spec's "either proceed with empty-dir
   ceremony or grant catalog a documented exception" wording.
2. The migration would force changing `services/catalog/tests/`
   import paths (`from bss_catalog.app import create_app` →
   `from app.main import create_app`), which violates the spec's
   hard constraint *"Existing services/catalog/tests/ must pass
   without modification."*
3. The `bss_catalog/` layout is actually MORE faithful to what
   catalog does — one repository file, three route files, one
   TMF schema. Forcing the standard structure dilutes the
   "shape mirrors function" property.
**Alternatives:** (a) Migrate with empty-dir ceremony + edit
test imports — rejected; violates the constraint. (b) Keep
package name `bss_catalog/` but reorganize internals
(`routes/` → `api/`, `repository.py` → `repositories/catalog_repo.py`,
`deps.py` → `dependencies.py`) — rejected; partial-migration
doesn't get the consistency win and breaks `from bss_catalog.repository`
test imports. (c) Add a `bss_catalog` shim re-export package —
rejected; cosmetic indirection that future maintainers will
remove.
**Consequences:** `services/catalog/` remains the one structurally-
distinct service. CONTRIBUTING.md's "How to add a new service"
section points contributors at `services/_template/` (the standard
template) — catalog is the documented exception, not the model.
If catalog ever gains policies (e.g. catalog write APIs in v0.7+),
the migration becomes natural at that point because the test-import
constraint can be relaxed alongside the larger change.

## 2026-04-23 — v0.6.0 — Per-service Dockerfile sed workaround retired (uv 0.11+ workspace builds)
**Context:** DECISIONS.md 2026-04-11 documented the per-service
Dockerfile `sed` workaround required because `uv` ≤ ~0.5 couldn't
resolve workspace dependencies inside a Docker build context that
only contained the service subtree. Tracked as a Phase 11 backlog
item; v0.6 evaluated empirically against `uv 0.11.3`.
**Decision:** Retire the sed workaround. The new template per
service:
```Dockerfile
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/<svc>/ services/<svc>/   # or portals/<name>/ + orchestrator/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN uv sync --package <svc> --frozen --no-dev
```
The COPY now includes the workspace root manifest +  `uv.lock`,
which is what `uv sync --package <svc>` needs to resolve the
workspace graph. Portal Dockerfiles additionally COPY `orchestrator/`
because portals depend on `bss-orchestrator` (workspace member).
**Empirical test:** All 11 containers (9 services + 2 portals)
build with the new template; all come up healthy within 23 s of
`docker compose up -d --wait` (compared to 18 s with the sed
workaround — overhead is ~5 s from larger COPY layers); image
sizes within 5% of the previous version.
**Alternatives:** (a) Keep the sed workaround — rejected; the
debt was a v0.1 expedient and uv has matured since. (b) Publish
internal packages to a local PyPI mirror — rejected; too much
infrastructure for a demo project. (c) Switch to a Bazel/Pants/Nx
build system — rejected; massive scope creep.
**Consequences:** Each Dockerfile dropped from ~28 lines to ~22.
Workspace dependency rewires (e.g., adding a new bss-* package)
no longer require touching every Dockerfile. The COPY pattern
also doubles as cache-friendly: changes to packages/ invalidate
all service builds, but changes to services/<svc>/ only invalidate
that one service. ARCHITECTURE.md "Per-service Dockerfile pattern"
section needs a small update to reflect the new template (drift
fix in PR 5).

## 2026-04-23 — v0.6.0 — `datetime.now()` doctrine grep guard added to CI
**Context:** SHIP_CRITERIA.md v0.1 entry: *"No business-logic module
calls `datetime.utcnow()` — `bss_clock.now()` is the only path.
Enforced by grep guard in CI (post-v0.1)."* The grep guard never
landed across v0.1-v0.5; one violation accumulated
(`cli/bss_cli/commands/usage.py`).
**Decision:** v0.6 adds `make doctrine-check` (a one-line
`rg 'datetime\.(now|utcnow)\(\)'` over business-logic paths,
excluding `**/tests/**`, `**/config.py`, the bss-clock package
itself, the `bss clock` CLI surface, and lines marked with
`# noqa: bss-clock`). The existing violation in `usage.py` is
fixed in the same commit. The guard is wired into both
`make verify` (local) and CI as a required check.
**Alternatives:** (a) Manual reviewer discipline — rejected;
empirically already failed once. (b) AST-based check — rejected;
overkill for a one-line grep. (c) Just delete the SHIP_CRITERIA
claim — rejected; the doctrine is right, only the enforcement
was missing.
**Consequences:** Future violations fail CI. The exemption list
(`config.py`, `bss clock` cmd surface, `# noqa: bss-clock`-annotated
sites) is small and explicit; expanding it requires a code-review
diff so the exception is reviewable.

## 2026-04-23 — v0.6.0 — TOOL_SURFACE.md tagged for aspirational vs registered tools
**Context:** TOOL_SURFACE.md listed 86 entries; 73 of them
matched `TOOL_REGISTRY` exactly, 13 were aspirational
placeholders (`billing.*` v0.2-deferred, `knowledge.*` Phase 11,
`admin.*` admin-only out of LLM registry) or non-tool concepts
(`audit.domain_event` is a table, not a tool;
`payment.payment_attempt` ditto;
`order.create.requires_verified_customer` is a policy rule).
A reader couldn't tell which entries were live LLM tools versus
roadmap placeholders.
**Decision:** v0.6 tags every aspirational / non-tool row
explicitly with a status badge in the description column
(`(planned vX.Y)`, `(admin only — not in LLM registry)`,
`(table — not a tool)`, `(policy rule — not a tool)`). The
registry-vs-doc sync test (`test_registry_matches_tool_surface_md`)
continues to enforce that every registered tool is documented;
v0.6 also adds the inverse direction (every doc-listed *tool*
that isn't tagged with a status badge must be in the registry).
**Alternatives:** (a) Delete the aspirational rows — rejected;
the placeholders document intent that ROADMAP.md alone doesn't
capture (e.g. specific tool argument shapes the future
implementation should match). (b) Move them all to ROADMAP.md —
rejected; ROADMAP.md is for versioned shipments, not per-tool
specs.
**Consequences:** Tool count line at the bottom of TOOL_SURFACE.md
states both numbers ("73 registered, 13 planned/non-tool").
Strangers reading the doc cold immediately see what's live vs
what's specced. The `_LLM_HIDDEN_TOOLS` mechanism unchanged.

## 2026-04-26 — v0.7.0 — Snapshot-at-order-time for subscription pricing
**Context:** v0.6 had subscription renewal read the price off the
catalog at renewal time. That looked fine while we never repriced
anything, but the moment an operator wanted to (a) run a CNY promo,
(b) raise PLAN_M from $25 to $30, or (c) add a PLAN_XS tier at $5,
existing customers' renewals would have silently changed price the
next billing cycle — a customer-trust violation, and in some
jurisdictions a regulatory one.
**Decision:** Each subscription row carries a price snapshot
(`price_amount`, `price_currency`, `price_offering_price_id`)
captured at order-creation time. Renewal charges the snapshot,
never the catalog. Catalog repricings only affect *new* orders.
Existing subscriptions move via an explicit operator-initiated
flow (`subscription.migrate_to_new_price`) with regulatory notice
(`notice_days`, default 30). A grep guard
(`rg 'get_active_price|get_offering_price' renewal_service.py`
returns empty) is part of the v0.7 doctrine sweep.
**Alternatives:** (a) Bump catalog version on each repricing and
rebuild every existing subscription — rejected; loses audit trail
of "what did the customer agree to at signup". (b) Re-quote on
every renewal and email the customer — rejected; the doctrine is
"bundled prepaid, no surprise charges" and re-quote is a surprise.
(c) Force the customer to re-acknowledge the new price each
renewal — rejected; UX nightmare and outside scope of "lightweight
MVNO".
**Consequences:** Migration 0007 backfills the snapshot for every
existing subscription before flipping the columns to NOT NULL.
Plan changes (Track 4) and operator price migrations (Track 5)
share the same renewal-time application path because they share
the same shape (pending offering + pending price + pending
effective_at).

## 2026-04-26 — v0.7.0 — Plan change applied at next renewal only (no proration)
**Context:** Real MVNOs let customers switch plans. Industry
default is some combination of: (a) prorate the remaining days of
the old plan, (b) charge a difference at switch, (c) reset the
allowance pool partially. All three paths add complexity, all
three add edge cases (what about a subscription mid-VAS-top-up?),
and none of them ship a better experience than "your switch takes
effect at next renewal, here's what your new bill will be".
**Decision:** `subscription.schedule_plan_change` records pending
fields. The next time `subscription.renew` fires after
`pending_effective_at`, it charges the new plan's snapshot,
swaps the offering, resets allowances per the new plan, and
clears pending. No proration, no immediate effect, no shortcut.
The customer's right-now allowance (from VAS top-ups, the
existing bundle) carries to the period boundary unchanged.
**Alternatives:** (a) Immediate switch with prorated refund —
rejected; the bundled-prepaid doctrine doesn't permit refunds,
and proration adds rating-engine complexity we explicitly avoid.
(b) Immediate switch with surcharge — rejected; surprise charges.
(c) "Switch plus VAS top-up" hybrid for "I want more data RIGHT
NOW and to switch plans" — rejected; that's two separate
operations, both already supported.
**Consequences:** Plan change is one tool call, idempotent only
in the cancel direction (one pending change at a time, customer
must `cancel_pending_plan_change` before scheduling a different
target). Renewal-time payment failure leaves pending intact so
manual retry / VAS-then-renew is still possible.

## 2026-04-26 — v0.7.0 — Lowest-active-price-wins for overlapping promo rows
**Context:** When promotional pricing lands, the natural shape is
a windowed `product_offering_price` row that overlaps the base
row temporarily. `get_active_price` then has to choose. The
choice is non-obvious: highest-priority promo? Most recently
inserted? Sum/aggregate? A coupon-engine could enforce any rule.
**Decision:** Lowest amount wins. Period. If a customer is
inside the promo window, they pay promo; outside, they pay base.
No priority field, no stack, no exclusion list, no eligibility
check. Two simultaneously active rows for the same offering are
fine and a documented pattern.
**Alternatives:** (a) Most recently inserted wins — rejected;
silent regression risk (a typo on a base-price update could
"promo" everyone to a new high). (b) Explicit promo flag with
priority — rejected; that's a coupon engine, out of scope. (c)
Reject any overlap as a configuration error — rejected; overlap
*is* the discount mechanism in v0.7.
**Consequences:** Operators run promos by inserting a windowed
price row at the discount amount. Misconfigured catalog (two
unintended overlapping rows) silently picks the lower; the
runbook for setting up a promo (`docs/runbooks/cny-promo.md`)
ends with "verify with `bss admin catalog show --at <window>`".
Future phases that introduce real campaigns / coupons revisit
this rule.


## 2026-04-26 — v0.8.0 — Account-first signup funnel (no anonymous purchase)
**Context:** v0.4 shipped an anonymous funnel: visitor fills the form,
the agent runs `customer.create` + `payment.add_card` + `order.create`
in one stream, and the customer record exists for the first time at
the bottom of that stream. v0.8 needs a login wall in front of the
portal. Inverting the funnel (identity first, customer second) is
strictly more work than gating the existing form, so the question
was whether the work was worth it.
**Decision:** Account-first. The visitor verifies their email at
`/auth/login` BEFORE the signup form is rendered. A `portal_auth.identity`
row exists from the moment they verify. The BSS-core customer record
is created later by the agent stream, and `bss_portal_auth.link_to_customer`
binds the identity to the customer the moment `customer.create` returns
a CUST-* id — atomic with the customer's existence, not gated on the
agent emitting a final message.
**Alternatives:** (a) Anonymous funnel + behind-the-scenes account
creation on submit — rejected; loses idempotency, identity continuity,
and the abandoned-cart hygiene that comes from having a verified-email
identity as the long-lived anchor. (b) Login wall at the activation
page only — rejected; activation already creates a customer row, so
this just shifts the same UX problem one step later. (c) Optional
"create account?" checkbox — rejected; conflates two flows and
encourages duplicate accounts.
**Consequences:** A returning visitor under the same email reuses
their existing identity (and customer, if previously linked). Mid-flow
bail leaves a linked identity, so the "I came back next week" path
just works. The anti-pattern "anonymous-with-deferred-account" is
banned in CLAUDE.md so future drift toward it requires an explicit
new decision. Hero scenario `portal_self_serve_signup_v0_8.yaml`
renamed from the v0.4 file and rewritten end-to-end. v0.4 file kept
as `portal_self_serve_signup_v0_4.yaml` (deprecated tag, no `hero`)
until v0.11 cleans up.

## 2026-04-26 — v0.8.0 — Magic-link + OTP, no passwords
**Context:** Login factors for the self-serve portal. Most signup
forms in the wild ask for a password; a few do passwordless.
Both are well-trodden paths. The decision had to weigh dev / ops
ergonomics for a tiny MVNO against customer expectation.
**Decision:** Magic-link + OTP only. No password field anywhere.
Both factors share the same login token store; verifying either
consumes the matched row and mints a session. Step-up auth re-uses
the same OTP shape, scoped to an `action_label`.
**Alternatives:** (a) Password + reset-via-email — rejected;
biggest breach surface, biggest support load (forgot-password
tickets), no operational upside for an MVNO that doesn't have a
password culture established. (b) SMS OTP — rejected; phone is
the product (the customer's line), so SMS-OTP is broken when the
line is blocked. Email is the one identity factor independent
of the BSS state. (c) Passkeys / WebAuthn — interesting for v1.x
stickiness; out of scope for v0.8.
**Consequences:** Smaller breach surface, no "forgot password"
ticket category, simpler runbook (rotate the pepper if a leak is
suspected; that invalidates in-flight tokens but not sessions).
Customers accustomed to password fields may be surprised — copy
on `/auth/login` ("No password — we'll email you a code") sets
expectations explicitly. Real MFA beyond step-up (authenticator
app, hardware key) is a v1.x story tied to the OAuth migration.

## 2026-04-26 — v0.8.0 — Server-side sessions over JWT
**Context:** The session token has to be revocable (logout, suspected
compromise, abuse) and slidingly expirable (24h max age but rotate
past TTL/2 to extend active customers). JWT can do this with a
refresh-token dance + a revocation list, or it can punt by treating
sessions as non-revocable. Server-side sessions can do it directly
with a row + `revoked_at` column.
**Decision:** Server-side sessions. The cookie carries an opaque
session id (32 chars URL-safe); the row in `portal_auth.session`
is the source of truth. Revocation is `UPDATE ... SET revoked_at = NOW()`.
Sliding rotation mints a new id and revokes the old in one transaction.
**Alternatives:** (a) JWT with short-lived access token + refresh —
rejected; more code, more state to track (refresh-token store with
its own revocation list), more complexity in the middleware. (b)
JWT with long-lived non-revocable tokens — rejected; revocation is
load-bearing for the abuse path. (c) JWT-with-blacklist — rejected;
that's a server-side session with extra cryptographic steps.
**Consequences:** Every authenticated request reads + updates one
row in `portal_auth.session`. Pool sized for that read pattern. For
the small-MVNO scale v0.8 targets, this is a non-issue; if scale
grows past one Postgres replica it's straightforward to move sessions
to Redis without changing the public API. JWT remains a Phase 12
option when per-principal claims (roles, tenants) become load-bearing
and a JWT validator is the cleaner contract for service-to-service
trust.

## 2026-04-26 — v0.8.0 — Email is identity, phone is product
**Context:** Telco customer portals routinely confuse "the customer
is identified by their phone number" with "logging in with the phone
number is sensible UX". The product is mobile lines, so the customer
inevitably has phone numbers — but using one of those numbers as the
login factor breaks the moment the line is blocked, suspended, or
ported.
**Decision:** Email is the unique identity. Phone numbers are products
the customer subscribes to via the funnel. The portal never asks
"what's your number?" at login. SMS-based OTP is not implemented in
v0.8 and is out of scope through v1.x; the sole verification channel
is email.
**Alternatives:** (a) Phone-as-login with email recovery — rejected;
breaks under the very state transitions the portal needs to support
(suspended / blocked subscriptions). (b) Either-or login — rejected;
the choice between "did you mean to sign in with phone or email"
is itself a UX problem, and the product team has been confused
about it for fifteen years across telcos. Pick one.
**Consequences:** A customer with a blocked subscription can still
log in to top up. A customer who ports out can still log in to see
their billing history. The "what's your number?" prompt only appears
during signup (MSISDN picker step) — never at the auth boundary.
Lost-email recovery is manual via human CSR (open a Case); self-serve
recovery for a lost-email-account is too footgun-prone for v0.8 and
is documented out of scope.

## 2026-04-26 — bugfix — `populate_existing=True` on FOR UPDATE balance reads
**Context:** `customer_signup_and_exhaust` hero scenario flaked
intermittently — two `usage.rated` events for the same subscription
arriving back-to-back occasionally produced `consumed=second_qty`
instead of `first_qty + second_qty`, causing the bundle to never
exhaust. The Phase 8 design (`SELECT ... FOR UPDATE` in
`get_balance_for_update`) was intended to serialize concurrent
decrements; verification showed the DB-side lock IS acquired
correctly. The bug was at the SQLAlchemy layer.
**Decision:** Add `.execution_options(populate_existing=True)` to
the `get_balance_for_update` SELECT. The Phase 8 lock semantics are
preserved (one-row pessimistic lock) and the cached Python object
is now overwritten with the fresh DB read after the lock is
acquired.
**Alternatives:** (a) `prefetch_count=1` on the consumer to remove
concurrency at the source — rejected; reduces throughput, doesn't
fix the underlying bug for any future caller of this repo method.
(b) Optimistic locking with compare-and-set + retry — rejected;
more code, harder to reason about, no net benefit. (c) Don't
selectinload `Subscription.balances` in `_repo.get` — rejected;
breaks every other call site that legitimately wants the eagerly-
loaded relationship.
**Consequences:** The fix is one line. Identity-map staleness vs
acquired-lock is a subtle SQLAlchemy trap — without
`populate_existing`, a SELECT FOR UPDATE that re-hits the DB still
returns the cached Python object with stale attributes, defeating
the lock at the application layer even though the DB is doing the
right thing. New regression test
`services/subscription/tests/test_usage_rated_race.py` reproduces
the cache-staleness mechanism in a single session and would FAIL
without the fix (verified). Documented inline in
`subscription_repo.py:get_balance_for_update`.

## 2026-04-26 — v0.9.0 — Named tokens at the BSS perimeter
**Context:** v0.3 introduced a single shared `BSS_API_TOKEN` carried
by every internal caller. With the v0.4/v0.8 self-serve portal now
sitting at the public-internet edge (behind a reverse proxy), a
leaked portal credential granted full orchestrator-equivalent access.
The portal is reachable from the public internet; the orchestrator is
not. Distinct exposure surfaces should rotate independently and leave
distinct audit trails.
**Decision:** Split the perimeter token into a `TokenMap`. The
default identity stays on `BSS_API_TOKEN`; new external-facing
surfaces get `BSS_<NAME>_API_TOKEN` env vars. The middleware loads
the map at startup, validates incoming `X-BSS-API-Token` against it
in constant time, and attaches the resolved `service_identity` to
the ASGI scope. Receiving services derive `service_identity` from
the token, never from a separate header. The self-serve portal in
v0.9 carries `BSS_PORTAL_SELF_SERVE_API_TOKEN` → `service_identity = "portal_self_serve"`.
The CSR console stays on the default token until v0.12.
**Alternatives:** (a) Jump straight to OAuth2/JWT — rejected, that's
Phase 12's full per-principal auth story and lifts roles/permissions
out of `auth_context.py` at the same time. v0.9 is the bridge.
(b) Leave a single token and rely on per-channel `X-BSS-Channel` for
audit attribution — rejected, the channel header is caller-asserted
and a leaked token still grants full access; the blast-radius point
needs distinct credentials, not just distinct labels. (c) Per-route
permission scoping on the named tokens — rejected as out of scope;
named tokens identify a *surface*, not a permission set. Phase 12
does scoping via JWT claims.
**Consequences:** Each external-facing surface now rotates on its
own cadence. Portal-token compromise leaves orchestrator and CSR
unaffected. Audit gains a critical dimension: SQL by
`service_identity` answers "which surface initiated this write?".
The model is forward-compatible with Phase 12 — the perimeter
middleware swap (token → JWT validator) is the only change per
service when OAuth lands. The Phase 12 trap of "rebuilding piecemeal"
is avoided because v0.9 deliberately ships only the token-map split,
not roles/permissions/per-principal claims.

## 2026-04-26 — v0.9.0 — Identity derivation from env-var name
**Context:** A `TokenMap` needs a stable, simple way to associate
each loaded token with an identity string. Two options: a separate
config block (e.g., a `BSS_TOKEN_MAP_JSON` env var) or convention
over configuration (env-var name → identity).
**Decision:** Derive identity from the env-var name.
`BSS_API_TOKEN` → `"default"`, `BSS_<NAME>_API_TOKEN` → `<name>`
lowercased. `BSS_PARTNER_ACME_API_TOKEN` → `"partner_acme"`. The
loader regex is `^BSS_(.+)_API_TOKEN$` plus the `BSS_API_TOKEN`
special case.
**Alternatives:** (a) Separate JSON config — rejected; one more file
to keep in sync with `.env`, easy for the two to drift. (b) A
required `BSS_*_API_TOKEN_IDENTITY` companion env per token —
rejected; doubles the env footprint without buying anything the
naming convention doesn't already give us.
**Consequences:** Adding a new named token is a one-line `.env`
change with no extra plumbing. The convention is documented in
`.env.example` and the rotation runbook so operators don't guess.
Doctrine: portal client code (`NamedTokenAuthProvider`) takes the
identity *label* as a constructor arg — that label is informational
on the outbound side only; the receiving side always re-derives from
its own validated map. Caller cannot assert identity.

## 2026-04-26 — v0.9.0 — Hashed token map storage (HMAC-SHA-256 with fixed salt)
**Context:** The middleware needs a fast, constant-time lookup from
incoming token to identity. Options for in-memory storage: raw
strings (simple, but raw env values live in process memory in dict
form, and a debug-level dump leaks them); HMAC-SHA-256 hashes with
a fixed salt (one-way, safe to log at debug level for ops diagnosis,
constant-time comparable via `hmac.compare_digest`); per-process
random salt (no diagnostic value across processes).
**Decision:** HMAC-SHA-256 with a constant salt baked into source.
The salt is not a secret — its purpose is one-wayness so the
in-memory map representation can be safely logged at debug level
without exposing the raw env value. Lookup hashes the incoming
header value with the same salt, then iterates the map under
`hmac.compare_digest`. Iteration does not short-circuit on first
match — total wall-time is independent of which entry matched.
**Alternatives:** (a) Plain dict of raw strings — rejected; debug
dumps and core dumps would leak the env value verbatim. (b)
Per-process random salt — rejected; an operator running `bss
config dump` on two processes can't compare hashes for sanity
checks (e.g., "are these two services running with the same token?").
**Consequences:** Operators can safely log the loaded map at debug
level for diagnosis. The salt-as-constant detail is a security
nuance documented in `api_token.py`; it is *not* an interface
callers should rely on. No `is_valid_token(value)` public helper —
all token validation goes through the middleware's 200/401 response.

## 2026-04-26 — v0.9.0 — Backfill `audit.domain_event.service_identity` to `'default'`
**Context:** Migration 0009 adds `service_identity` to
`audit.domain_event`. Existing rows predate v0.9; how should the
column be populated? Three options: leave NULL (interpret later),
backfill `'default'` in the migration with NOT NULL applied after,
or backfill in v0.10 with a NULL-allowed column in v0.9.
**Decision:** Backfill `'default'` in the same migration, then apply
NOT NULL with `server_default='default'`. Pre-v0.9 rows arrived via
the v0.3 single-token regime which v0.9 maps to identity `"default"`
— the historically-correct value, not an "unknown" placeholder. The
NOT NULL constraint guarantees the column always has a meaningful
value for SQL pivots and prevents a future paper-cut where some
straggler insert path forgets to populate it.
**Alternatives:** (a) Leave nullable forever — rejected; "what does
NULL mean here" creates an ongoing interpretation tax on every
SQL query. (b) Defer backfill to v0.10 — rejected; same
half-finished trap as the v0.7 price-snapshot migration that we
explicitly call out as an anti-pattern in the v0.9 phase doc.
**Consequences:** Forward-compatible — every row in
`audit.domain_event` now carries a meaningful `service_identity`,
including historical rows. The v0.9 phase doc's "audit by surface"
queries (in the rotation runbook) work correctly against pre-v0.9
data: a leak detection query on the past 90 days returns sane
counts because the historical baseline is `'default'`, not `NULL`.

## 2026-04-27 — v0.10.0 — Post-login self-serve writes go direct via `bss-clients` (doctrine carve-out)
**Context:** v0.4 established "every portal write goes through the
LLM orchestrator via `agent_bridge` → `astream_once`" as a blanket
rule. That rule existed because the v0.4 demo's purpose was to show
the agent pattern works end-to-end on a customer-facing surface. By
v0.10 the purpose has shifted: the post-login dashboard, top-up,
COF management, eSIM redownload, cancel, contact update, charge
history, and plan change are routine flows a customer performs
daily. Routing each of those through an LLM round-trip costs ~2–5s
of latency, burns tokens for deterministic operations, and obscures
the audit trail (the LLM's tool call vs. the customer's intent). The
doctrine question: do we keep the v0.4 blanket rule, or carve out
authenticated post-login self-serve as a direct-API surface?
**Decision:** Carve out authenticated post-login customer self-serve
as a direct-API surface. Route handlers behind `requires_linked_customer`
may call `bss-clients` directly. The customer principal is bound
from `request.state.customer_id` (verified session, never form/query
input); per-resource ownership policies (`check_subscription_owned_by`,
`check_service_owned_by`, `check_payment_method_owned_by`) gate every
cross-resource access; sensitive writes require step-up auth via the
`requires_step_up(label)` dependency, with `SENSITIVE_ACTION_LABELS`
as the greppable source of truth. One route = one `bss-clients` write
(or zero) — no composition. The signup funnel (v0.4 / v0.8) and the
chat surface (v0.4–v0.11) continue going through the orchestrator;
they remain the surfaces where the LLM is a feature, not a tax.
**Alternatives:** (a) Keep the v0.4 blanket rule — rejected; the
latency cost on a daily-use page like the dashboard is large and
visible, and the LLM adds nothing on a deterministic top-up. (b)
Make everything direct, including signup and chat — rejected; that
collapses the v0.4 demo's signature artifact (the agent log
streaming during signup) and pre-empts v0.11's chat scoping work.
(c) Allow composition in route handlers — rejected; route-handler
composition is how silent data drift sneaks in (commit A succeeds,
commit B fails, no rollback). Service-side composite operations or
the orchestrator are the right place for "do A then B".
**Consequences:** Eight new self-serve pages run sub-second and
deterministic. The doctrine is narrower than "everything direct" —
it explicitly preserves orchestrator-mediation for signup and chat,
and Phase 12's per-principal OAuth2 swap still lands at the same
seam (`auth_context.py`). Greppable doctrine guards enforce the
boundary: `rg 'astream_once' portals/self-serve/bss_self_serve/routes/`
must match only chat + signup; `rg 'customer_id\s*=\s*(form|body|query|path)'`
must stay empty in post-login routes. The cross-customer attempt
suite is non-negotiable — every sensitive route gets a "try as the
wrong customer" test that asserts 403 + audit row. Future deliverables
that propose extending the carve-out (e.g., "make the chat direct
because it'd be faster") require their own DECISIONS entry; they
don't ride on this one.

## 2026-04-27 — v0.10.0 — Default LLM model swapped from MiMo v2 Flash to google/gemma-4-26b-a4b-it
**Context:** Phase 9 picked `xiaomi/mimo-v2-flash` as the default
dev/hero-scenario model: $0.09/M prompt, $0.29/M completion, 262K
context, clean instruction-following on the Phase 8 pre-flight.
That choice held through v0.9. During v0.10 development the LLM
hero scenarios (`llm_troubleshoot_blocked_subscription`,
`portal_csr_blocked_diagnosis`, `portal_self_serve_signup_v0_8`)
started spiking from steady ~10–17s/run to 50–180s/run, with
intermittent failures (10/11, 14/15 step-passes — never the same
scenario twice in a row, never the same step). The pattern was a
provider-side latency / availability hiccup on Mimo, not a portal
or scenario regression: re-running with no code changes flipped
results, and the failures landed on different scenarios across
runs. Hero "three runs in a row green" stopped being a deterministic
ship gate.
**Decision:** Switch the default model in `.env` (and `.env.example`)
to `google/gemma-4-26b-a4b-it`, also via OpenRouter. Three back-to-back
hero runs immediately after the swap: 9/9 PASS each, with steady
durations (LLM steps 10–15s, no spikes). The phase-doc historical
record (PHASE_09 / PHASE_10 / V0_2 / V0_4 / V0_5 / V0_11) keeps the
MiMo references — those are *frozen* records of decisions made at
the time, not a living description. Live surfaces (`CLAUDE.md` tech
stack, `.env.example`, the operational diagnostic comment in the
LLM hero scenario YAML) are updated to point at the current
default.
**Alternatives:** (a) Keep MiMo and absorb the flakes via retries —
rejected; the doctrine "if the LLM scenario is flaky, the fix is the
semantic layer, not the test" (PHASE_10) means we don't paper over
provider hiccups with retry loops. (b) Swap to Sonnet 4.6 / Opus
4.7 — rejected for the *default*; reserved as the explicit override
for cases where tool-call quality matters more than cost. The
`BSS_LLM_MODEL` env var is and remains the single switch; no code
hardcodes a model name. (c) Backfill the historical phase docs to
say "Gemma" — rejected; phase docs are append-only frozen records
and rewriting them would lie to future readers about what was true
when. The DECISIONS log is the running history; this entry is the
canonical "swap happened on 2026-04-27".
**Consequences:** Hero-scenario flakes stop. Cost / latency / context
properties are comparable to MiMo for our workload (small number of
tool calls per scenario). The swap is reversible — flip
`BSS_LLM_MODEL` back, restart, done. If Gemma later develops its own
issues, the next switch is a one-line env change and another
DECISIONS entry; the abstraction layer (OpenRouter via openai SDK)
absorbs it. The Phase-9 design doctrine "code never hardcodes a
model name — only `.env` does" is what makes this swap a one-line
change in production, not a refactor.

## 2026-04-27 — v0.10.0 PR 8 — Email-change cross-schema atomic write (doctrine bend)
**Context:** v0.10 PR 8 ships email-change on the self-serve portal.
The flow has two atomicity-critical writes that must commit
together: ``crm.contact_medium`` (the email row on the customer's
party) and ``portal_auth.identity.email`` (the row the login flow
reads). If they don't commit together, the customer's CRM record
shows the new email but they still log in with the old one (or
vice versa), and there's no easy recovery path. V0_10_0.md "Do not
silently downgrade the email-change flow's atomicity" calls this
out as the explicit anti-pattern.
The two affected schemas live in the same Postgres instance, so
"a single transaction spanning both schemas" is the right answer
the phase doc points at. But the natural way for the portal to
write to ``crm.contact_medium`` is via the CRM service's HTTP API
(through bss-clients), which has its own commit boundary. Doing
that plus a separate ``portal_auth.identity`` write in the portal
is exactly the half-commit trap.
**Decision:** Add ``bss_portal_auth.email_change.verify_email_change``
that writes to BOTH ``crm.contact_medium`` AND
``portal_auth.identity.email`` (plus the
``portal_auth.email_change_pending`` row) in a single
``AsyncSession`` transaction. The function is the one named place
where the cross-schema write lives. The portal route handler
(``routes/profile.py::email_change_verify_submit``) opens a session,
calls the function, and either commits everything or rolls back
everything; the caller never sees a half-state.
This is a deliberate, narrow exception to the project's
"writes go through service-side policies" rule. The justification:
splitting the update across two HTTP calls (CRM, then portal_auth)
is exactly the half-committed state the doctrine forbids, and the
two schemas live in the same Postgres instance so a single
transaction spans them naturally. Email-change is the ONLY flow
in v0.10–v0.11 that crosses the schema boundary; future flows
that need similar atomicity must either (a) add a service-side
composite operation, (b) use a documented saga with explicit
compensation, or (c) extend this exception with their own
DECISIONS entry. The default remains "go through the service
HTTP API."
**Alternatives:** (a) Add a server-side composite endpoint in CRM
that ALSO writes to ``portal_auth.identity.email`` — rejected;
forces the CRM service to know about the portal_auth schema, a
layering violation that bleeds across other future portal-vs-CRM
changes. (b) Saga with compensation: portal writes CRM via HTTP,
then portal_auth, with a compensating CRM rollback if portal_auth
fails — rejected per the phase doc's "occasionally end up with
mismatched states and no easy way to detect or recover" warning;
the compensation itself can fail and you're back to the same
problem. (c) Two-phase commit / XA — rejected as massive
infrastructure overkill for a once-per-customer-lifetime flow.
**Consequences:** The email-change atomicity claim is enforceable
and tested. ``test_routes_profile.py::test_email_change_verify_rolls_back_on_partial_failure``
plants a synthetic mid-transaction failure and asserts NEITHER
schema's row was flipped — that's the load-bearing test for the
"atomic" claim. The new ``bss_portal_auth.email_change`` module
is small (~250 lines) and reviewable; future changes that touch
it get extra scrutiny. The doctrine bend is documented in three
places: this DECISIONS entry, the module-level docstring on
``email_change.py``, and a comment in ``routes/profile.py``.
Re-introducing similar cross-schema writes elsewhere requires its
own justification — the prohibition still applies in the general
case.

## 2026-04-27 — v0.10.0 — eSIM redownload is a read-only re-display, not a real rearm
**Context:** v0.10 PR 6 ships ``/esim/<subscription_id>`` so a
customer can see their LPA activation code + QR after signup. The
question that came up during implementation: is this the
production-realistic flow? In a real GSMA SGP.22 setup, an eSIM
profile is bound at install time to the device's eUICC EID. Once
the profile is in ``Installed`` state on SM-DP+, a redownload
(factory reset, new device, profile lost) typically requires:
(a) operator-side trigger — BSS calls SM-DP+ to release the
profile or revoke + mint a new one; (b) SM-DP+ moves the profile
back to ``Released`` (or issues a fresh activation code with a new
ICCID/IMSI); (c) the customer scans the new code on the new /
reset device. Some MVNO setups treat the activation code as a
stable string for the lifetime of the line (deferred-binding
profile model), but most operators run the rearm step explicitly.
**Decision:** Ship a deliberately simplified read-only flow in
v0.10. The route reads the subscription (ownership-checked) +
inventory.esim_profile.activation_code and renders the code + an
inline PNG QR. No SM-DP+ call, no rearm, no device-binding
semantics, no state change. The simplification is honest in code
and documented in three places: a CLAUDE.md scope-boundary bullet,
a ROADMAP non-goal entry naming the future SOM task
(``ESIM_PROFILE_REARM``), and a route docstring that points at
this DECISIONS entry. The template caption tells the customer that
if the code isn't working on a new device they should contact
support — the operator-side trigger lives outside the customer
self-serve surface for now.
**Alternatives:** (a) Punt eSIM from v0.10 entirely — rejected;
customers couldn't see their LPA at all, including the original
code from signup, which is the most common request. (b) Land a
thin "Reinstall on new device" CTA that opens a CSR ticket
(``case.open(category=esim_rearm)``) — rejected for v0.10; adds a
new policy + ticket category mid-phase, and the operator-side
rearm work is missing on the back end. Better to add the CSR-
ticket bridge in v0.12 alongside the real SM-DP+ adapter than to
half-ship it now. (c) Build the real rearm flow now — rejected;
the SM-DP+ adapter is a real-NE-adapter integration concern and
explicitly out of scope per CLAUDE.md. Half-implementing it
against the simulator gives a false sense of completeness.
**Consequences:** Customers see the same activation code each
time — fine for their original device, fine for v0.10 demo /
dev. The route is fast, ownership-checked, and produces a
``portal_action`` audit row only on the admin ``?show_full=1``
debug branch (no audit row for the regular last-4 view — it's a
non-sensitive read). Future work is well-scoped: v1.x adds the
``ESIM_PROFILE_REARM`` SOM task, a ``provisioning.rearm_esim_profile``
policy, the ``inventory.esim_profile`` state transition, and a
new POST route on top of the existing read-only one. The seam is
clean — the simplified read-only re-display stays as the cheap
default; the rearm bolts on without changing the URL or the
customer-facing template caption.

## 2026-04-27 — v0.11.0 (committed) — Signup funnel migrates to direct API; v0.4 agent-log artifact retired
**Context:** v0.10's direct-API carve-out for post-login self-serve
exposed a follow-on question: should the signup funnel stay
orchestrator-mediated? It was made LLM-driven in v0.4 as the demo
artifact for "the agent pattern works on a customer-facing flow"
— the agent-log widget streaming during signup was the
project's signature visual proof that BSS-CLI is LLM-native. By
v0.10 the cost showed up in the hero suite: ``portal_self_serve_signup_v0_8``
takes ~85 seconds wall-time per run because it's 5–8 LLM
round-trips at 8–15s each. None of those round-trips need
LLM judgment — signup is a deterministic sequence (pick plan
→ MSISDN → KYC attest → COF → place order → wait for SOM
activation), each step has one correct next step, no branching
benefits from reasoning. The v0.10 carve-out's logic — "v0.4's
purpose was demoing the agent pattern; v0.10's purpose is daily
use; routine flows shouldn't pay the LLM tax" — applies word-for-
word to signup.
**Decision:** Migrate the signup funnel from orchestrator-mediated
to direct API calls from route handlers in v0.11.0. Same shape as
v0.10 post-login routes: one route → one BSS write,
ownership-where-applicable, audited where applicable, sub-second
per step (excluding the SOM activation poll). URL shapes preserve
exactly so existing customer links keep working. The agent-log
SSE widget and ``agent_bridge.drive_signup`` are deleted from the
portal; ``agent_events.py`` is replaced by a small deterministic
progress UI that polls ``order.get`` every 500ms and ticks the
five-step timeline. The v0.4 demo artifact is retired from the
primary signup path; the educational story (watching an agent
drive a customer flow) survives via the existing
``llm_troubleshoot_blocked_subscription`` and ``portal_csr_blocked_diagnosis``
heroes (LLM adds value where judgment is required) plus the chat
surface (still orchestrator-mediated, scoped further in v0.12).
The chat surface becomes the **only** orchestrator-mediated
route post-v0.11. The CLAUDE.md anti-pattern splits one more time:
``(v0.4–v0.10 / signup + chat) → orchestrator``; ``(v0.11+ / chat
only) → orchestrator``. The new ``phases/V0_11_0.md`` is the
implementation guide; existing chat-scoping work (was V0_11) is
pushed to V0_12.
**Alternatives:** (a) Keep signup orchestrator-mediated for the
demo artifact — rejected; the cost (~85s per signup, several LLM
calls per customer at scale) is too high for a flow that doesn't
need LLM judgment, and the daily-use principle that anchored
v0.10 applies identically here. (b) Dual-path with both
``/signup/agent/*`` (LLM demo) and ``/signup/*`` (direct) —
rejected for v0.11; preserving the demo as a separate path is a
feature flag that nobody owns, with rot risk. The git history at
``tag v0.10.0`` is the demo archive. If a future deliverable
genuinely needs the agent-driven path back, that's a fresh
DECISIONS entry, not a feature flag we ship preemptively. (c)
Defer the decision to a v0.11 open question — rejected; we made
the call, capture it now so the doctrine evolution stays
trackable.
**Consequences:** v0.11 hero suite drops the 85s signup runtime
to under 10s (target). Phase ordering is preserved cleanly: v0.10
post-login → v0.11 signup direct → v0.12 chat scoping → v1.0
real Singpass / Stripe / SM-DP+ swap. The doctrine boundary is
dramatically simpler: only ``/chat`` is orchestrator-mediated
post-v0.11, and v0.12 then narrows that to a per-customer scoped
profile with caps + escalation. Future "should X be LLM-mediated"
questions get a clean answer: routine flows go direct, judgment
flows go through the chat surface. The v0.4 historical record
(phase doc, DECISIONS entry, git tag) stays intact — phase docs
are append-only frozen records and we don't backfill them.


## v0.12.0 — `*.mine` wrappers as the prompt-injection containment layer

**Date:** 2026-04-27
**Phase:** v0.12.0 PR2 / PR3
**Decision:** The chat surface invokes ``astream_once`` with
``tool_filter="customer_self_serve"`` so the LLM only sees the
profile's curated subset. Inside that profile, every tool that
takes any owner-bound argument is a ``*.mine`` / ``*_for_me``
wrapper that:

1. Reads ``customer_id`` from
   ``orchestrator.auth_context.current().actor`` — never from a
   parameter. Signatures simply omit ``customer_id`` /
   ``customer_email`` / ``msisdn``. A startup self-check
   (``tools/_profiles.validate_profiles``) inspects every
   registered ``*.mine`` tool's signature at orchestrator import
   time and raises if any forbidden parameter slipped in.

2. For wrappers that accept a resource id (``subscription_id``),
   pre-checks ownership against the bound actor and refuses with
   a structured ``policy.<tool>.not_owned_by_actor`` error. The
   server-side policies remain the primary boundary; the
   wrapper's pre-check produces a uniform observation across
   every tool so the LLM's behaviour to a prompt-injection
   attempt is identical irrespective of which tool was tried.

3. Calls the canonical tool internally with the actor-bound id.

**Alternatives rejected:** (a) Re-use the canonical tools
unchanged + rely on server-side policies alone. Rejected — leaves
the prompt-visible surface unrestricted, which means
prompt-injection attempts at least *try* before being rejected;
each rejection is an audit row + a CSR-visible interaction. The
narrowness is a feature. (b) Generate the wrappers from the
canonical registry. Rejected — auto-derivation is exactly how
"add `customer.find_by_msisdn_mine` for the chat" creeps in. The
list in ``_profiles.py`` is curated; widening it requires the
runbook §6.4 security review checklist.

**Consequences:** The chat surface's autonomous reach is
explicitly bounded. The wrappers + server policies + output
trip-wire form a defence-in-depth stack. Adding a chat capability
in v1.x means adding (a) a wrapper if needed, (b) a profile
entry, (c) an `OWNERSHIP_PATHS` entry, (d) a runbook update — the
order is intentional and documented.

## v0.12.0 — Output ownership check as P0 trip-wire

**Date:** 2026-04-27
**Phase:** v0.12.0 PR4
**Decision:** ``orchestrator/bss_orchestrator/ownership.py`` ships
``assert_owned_output(tool_name, result_json, actor)`` and an
``OWNERSHIP_PATHS`` registry mapping each customer-profile tool
to the JSON paths in its response that must equal ``actor``.
``astream_once`` runs the check after every non-error
``ToolMessage`` whose source tool is configured. On mismatch the
stream terminates with an ``AgentEventError(message=
"AgentOwnershipViolation: <tool>")``; the chat route catches
that and renders a generic safety reply. A CRM
``log_interaction`` row is written on the actor's record (which
emits an ``audit.domain_event`` server-side via the v0.1
auto-logging path) so ops can investigate.

**Why a trip-wire and not a primary gate:** Server-side policies
already enforce ownership on every write. The trip-wire exists
for the day a policy misses a case — to fail loudly rather than
ship cross-customer data to the customer. A real trip is a P0
incident; the runbook section "Investigating an ownership-check
trip" carries the on-call query patterns.

**Alternatives rejected:** (a) Skip the check, trust policies.
Rejected — the cost of being wrong (data exfiltration to the
wrong customer through an LLM-rendered chat reply) dwarfs the
cost of running one path-walk per tool result. (b) Make the
check a primary gate (block writes pre-flight). Rejected —
duplicates the policy logic at a different layer and creates
two sources of truth for "is this customer authorised". The
existing seam is fine.

**Consequences:** The 14-day soak gate is "zero ownership-check
trips." A trip during the soak is fix-and-rerun territory.
The startup self-check (extension of ``validate_profiles``)
asserts every ``customer_self_serve`` tool has an
``OWNERSHIP_PATHS`` entry — coverage gaps fail at deploy.

## v0.12.0 — $2/month default chat cost cap

**Date:** 2026-04-27
**Phase:** v0.12.0 PR5
**Decision:** ``BSS_CHAT_COST_CAP_PER_CUSTOMER_PER_MONTH_CENTS=200``
+ ``BSS_CHAT_RATE_PER_CUSTOMER_PER_HOUR=20`` are the v0.12
defaults. ``chat_caps.check_caps`` reads the current month's
``audit.chat_usage`` row + a per-process in-memory hourly
sliding window; a trip on either short-circuits the chat route
to a templated cap-tripped SSE response. ``record_chat_turn``
upserts cost + request count after each completed turn,
deriving cents from OpenRouter token counts × per-model rate
(``MODEL_RATES_USD_PER_M_TOK``).

**Why these numbers:** $2/month covers ~150 turns at
``google/gemma-4-26b-a4b-it`` pricing — generous for normal use,
small enough to bound a runaway customer (or a malicious chat
attempt that gets through the per-IP cap). 20/hour is loose
enough that a focused customer doesn't hit it during a real
support session, tight enough to slow obvious abuse.

**Alternatives rejected:** (a) Hard-code in code. Rejected —
the soak's needs differ from prod; per-customer overrides are
likely to land in v1.x. (b) Per-tier caps based on the
customer's plan price. Rejected for v0.12 — that's billing
infrastructure we don't have. v1.x can layer it on top of the
existing seam.

**Consequences:** The route is **fail-closed**: any error in
``check_caps`` (DB unreachable, etc.) returns
``CapStatus(allowed=False, reason="cap_check_failed")`` so the
LLM is never invoked on uncertainty. The runbook section
"Investigating cap-tripped customer reports" covers operator
overrides + sanity checks.

## v0.12.0 — Five escalation categories as a hard list

**Date:** 2026-04-27
**Phase:** v0.12.0 PR6
**Decision:** Fraud, billing dispute, regulator complaint,
identity recovery, bereavement. Plus ``other`` as the
CSR-triaged catch-all. The list lives in three places that must
stay in sync: the ``EscalationCategory`` Literal in
``orchestrator/bss_orchestrator/types.py``, the soak corpus
keys in ``scenarios/soak/corpus.py``, and the customer-chat
system prompt in ``customer_chat_prompt.py``. A test
(``test_escalation_categories_match_orchestrator_enum``) compares
the soak corpus keys to the enum.

**Why these five and not four or six:** Each is a category
where the AI has either regulatory exposure (regulator
complaint), fraud risk (fraud, identity recovery), legal /
emotional sensitivity (bereavement), or money disputes that
must reach a human (billing dispute). Anything outside the five
is either the AI's job (top up, plan change, balance) or
``other`` for CSR triage. Adding a sixth is a doctrine decision
because it widens the "I'll let a human handle this" shape and
each addition costs a real CSR reading a real transcript.

**Alternatives rejected:** (a) No fixed list — the AI decides
when to escalate. Rejected — that's prompt-drift territory and
the threshold for "I forgot my password" → escalate is a
real-pager-call away from "I forgot my password" → use the
self-serve recovery flow. (b) Wider list (account close,
roaming questions, complaint about service quality, etc.).
Rejected — those have well-defined direct routes; escalation
should not be the AI's escape hatch for hard questions.

**Consequences:** The customer-chat prompt encodes the five
verbatim with concrete examples. The wrapper accepts the
``EscalationCategory`` enum so unknown categories cannot reach
the case-open path. Soak corpus has 5 trigger phrases per
category, fired at 1%/customer/day so all five exercise over
the 14-day window across 100 customers.

## v0.12.0 — Transcript hashing + dedicated ``audit.chat_transcript`` table

**Date:** 2026-04-27
**Phase:** v0.12.0 PR1 / PR6
**Decision:** Transcripts addressed by SHA-256 of the body.
``crm.case.chat_transcript_hash`` is a nullable Text column
linking a case to its triggering transcript;
``audit.chat_transcript(hash, customer_id, body, recorded_at)``
holds the bodies. Inserts are idempotent
(``ON CONFLICT DO NOTHING``); the CRM service re-computes the
hash and rejects mismatches so the column cannot be poisoned
with a body that does not match its key.

**Why a separate table and not a column on ``crm.case``:** Three
reasons. (a) Transcript bodies are bigger than typical case
fields and we don't want to pay row-width for every case. (b)
Multiple cases could legitimately reference the same transcript
(unlikely but possible). (c) The retention runbook needs to
archive transcripts independently of cases — case-closed-90d
+ archive — and a separate table makes that operation a
``DELETE FROM audit.chat_transcript WHERE ...`` rather than a
case-row migration.

**Alternatives rejected:** (a) Inline transcript on the case
row. Rejected for the row-width + retention reasons. (b)
Object storage (S3) addressed by hash. Rejected for v0.12 —
adds an infrastructure dependency we don't otherwise need;
v1.x can swap if transcripts grow large. The current Postgres
column is fine for the 14-day soak's hundreds-of-rows
expectation.

**Consequences:** CSR retrieval via ``case.show_transcript_for``
is a single GET. Archive is a single DELETE filtered by case
state + closed-at. The hash is a content-fingerprint; if a
transcript needs to be reconstructed for legal hold, the case
row + the body row form a complete record without reaching
into a separate object store.


## 2026-05-01 — v0.13.0 No staff-side auth

**Decision:** Retire the Phase-12 staff-side OAuth/RBAC ambition. The
v0.5 stub-login pattern is gone (every route, template, module, and
test deleted in PR7). The operator cockpit (CLI REPL canonical;
browser veneer at port 9002) runs single-operator-by-design behind a
secure perimeter. `actor` for cockpit-driven downstream calls comes
from `.bss-cli/settings.toml` — descriptive only, not verified. The
audit trail is "who set the actor name + when" rather than "who
typed their password".

**Why:** BSS-CLI is operated by a 1–3 person team. OAuth + Keycloak +
roles + per-tool ACLs adds operational drag (rotation, account
lifecycle, role drift) without proportional security gain at this
scale. The trust boundary is the perimeter (Tailscale, VPN, local
LAN), not a login wall. CLAUDE.md's seven-motto principle 4 —
"CLI-first, LLM-native" — is incompatible with a multi-user staff
auth surface; doctrinal honesty argues for a clean retirement.

**Alternatives rejected:**

- **Keep stub login as a placeholder** until Phase 12 ships the real
  thing. Rejected: the placeholder pretended to be auth and confused
  contributors who reasonably assumed it'd be tightened later.
- **Ship a real OAuth/JWT flow now.** Rejected: scope creep, weeks
  of work, drag for a 1–3 person team. The operational cost is real
  and unbudgeted.
- **Defer the decision.** Rejected: deferral leaves the v0.5
  artifact in place and signals "we'll fix this later". v0.13 is
  the right moment to make the call explicit.

**Consequences:** No `services/auth`. No 8-coarse-roles model. No
fine-permissions = tool-name model. The cockpit's `operator_cockpit`
profile is a coverage assertion (full registry minus `*.mine`
wrappers), not a permission gate. If a future deployment genuinely
needs multi-operator separation, the path is multi-tenant carve-out
(one cockpit container per operator namespace), not a login wall on
the same container. Customer-side auth (v0.8 portal session,
v0.10 step-up, v0.12 chat scoping) is unchanged — this decision
narrows the doctrine to "no STAFF auth", not "no auth".

## 2026-05-01 — v0.13.0 REPL canonical, browser veneer

**Decision:** The CLI REPL (`bss`) is the canonical operator
cockpit. The browser at `localhost:9002/cockpit/<id>` is a thin
veneer over the same Postgres-backed `cockpit.session` /
`cockpit.message` / `cockpit.pending_destructive` tables. Both
surfaces drive `astream_once(transcript=, actor=, channel=,
service_identity="operator_cockpit", tool_filter="operator_cockpit",
system_prompt=)`; the only difference is the channel name (`"cli"`
vs `"portal-csr"`) on outbound bss-clients calls.

**Why:** CLAUDE.md doctrine 4 — "CLI-first, LLM-native". The REPL
already does 80% of the shape (slash commands, ASCII renderers,
inline tool-call observation). Building a separate browser-only
surface would duplicate the conversation model, the pending-
destructive contract, the focus pin, the 360 renderer dispatch.
One implementation, two surfaces. Operators who live in the
terminal use `bss --session SES-...`; team members who don't open
the same session in a browser tab.

**Alternatives rejected:**

- **Browser-only surface.** Rejected: contradicts the CLI-first
  doctrine; the REPL is faster for the operator who's already in a
  terminal.
- **REPL-only surface.** Rejected: shipped MVNOs sometimes have
  team members who prefer browser UIs (account managers, billing
  analysts). The shared store costs ~200 lines of FastAPI for the
  veneer; well worth the inclusion.
- **Two stores, one synchronization layer.** Rejected: that's a
  v0.5 mistake (in-memory `Session` + portal `OperatorSessionStore`
  + `AgentAskStore`). v0.13 collapses the lot to one Postgres-backed
  store; cross-surface drift becomes "the same SELECT against the
  same row", not a bidirectional sync problem.

**Consequences:** Slash-command parity is a doctrine target — every
REPL command must have a browser affordance and vice versa. The
in-memory `Session` class in `orchestrator/bss_orchestrator/session.py`
is retired; `astream_once(transcript=)` is the only multi-turn shape
(PR6 wires the transcript parser into the LangGraph messages list so
the model actually sees prior turns).

## 2026-05-01 — v0.13.0 OPERATOR.md prepended to system prompt

**Decision:** `.bss-cli/OPERATOR.md` is the operator's editable
contract with the agent. The cockpit's
`bss_cockpit.build_cockpit_prompt(operator_md, ...)` prepends it
verbatim to every system prompt. Hot-reloaded on mtime; no process
restart. Bootstrapped on first run from a `.template` sibling (or
from an embedded default if templates aren't on disk — needed for
container deploys).

**Why:** Operator persona + house rules (currency, tone,
escalation rules) change more often than agent behavior — making
them code requires a deploy; making them config (TOML) requires a
schema; making them markdown lets the operator iterate by `vim`.
Claude-Code-shape: the agent sees the operator's voice every turn.

**Alternatives rejected:**

- **Operator persona in `settings.toml`.** Rejected: TOML's prose
  ergonomics are bad; multi-paragraph house rules become an array
  of strings; the editor experience is worse than a markdown file.
- **Operator persona as code.** Rejected: deploy-required iteration
  is a non-starter for an operator-tunable preference.
- **Per-customer OPERATOR.md.** Rejected: scope creep. One global
  persona file; if "different operators want different defaults",
  edit `settings.toml.actor` and let the persona stay shared (or
  fork the file by symlink and switch links).

**Consequences:** Operators can drift the cockpit into prompt-
injection territory by writing "ignore all policy violations" into
`OPERATOR.md`. That's the operator's choice — the trust model is
"the perimeter delegates to the operator". CLAUDE.md anti-patterns
flag the foot-gun explicitly so a future operator doesn't reach for
it as an "easy override" without realising they've moved the trust
boundary. The cockpit's safety contract (propose-then-`/confirm`,
escalation list) is **code**-defined in
`bss_cockpit.prompts._COCKPIT_INVARIANTS` — not editable from
markdown.

## 2026-05-01 — v0.13.0 One Conversation store, two surfaces

**Decision:** Cockpit conversations live in `cockpit.session` /
`cockpit.message` / `cockpit.pending_destructive` (alembic 0014).
Both surfaces consume; neither reimplements. The store is owned by
the new `bss-cockpit` workspace package. Customer chat keeps its
own per-customer conversation store (`audit.chat_transcript`,
v0.12) — different scoping concern, different lifecycle.

**Why:** v0.5 invented `OperatorSessionStore` (cookie → operator id)
+ `AgentAskStore` (one-shot ask → SSE) + an in-memory `Session`
class in the orchestrator (multi-turn graph state). Three stores,
no convergence; resuming an exited REPL was impossible; the browser
saw nothing the REPL had typed. v0.13 collapses all three into one
Postgres-backed conversation. `astream_once(transcript=...)` (PR6)
feeds prior turns into the LangGraph messages list so multi-turn
coherence actually works.

**Alternatives rejected:**

- **Per-surface stores with sync.** Rejected: every sync layer is a
  bug source.
- **In-memory + checkpoint to disk.** Rejected: two surfaces, one
  process means one cache; the moment the operator runs the REPL
  alongside a browser, the in-memory shadow drifts.
- **Reuse `audit.chat_transcript` for cockpit.** Rejected: customer
  chat's per-customer scoping doesn't fit the operator's per-session
  model; mixing the two muddles the audit trail.

**Consequences:** Adding a store column requires an alembic
migration. Schema drift is impossible (one schema, one source).
Future convergence with the customer-chat store is a post-v0.13
question — the two stores share API shape but not lifecycle, and
the doctrine accepts the duplication.

## 2026-05-01 — v0.13.0 Inline /confirm for destructive actions

**Decision:** Destructive cockpit operations follow propose →
operator types `/confirm` (REPL) or clicks the button (browser) →
next turn runs `allow_destructive=True` and consumes the
`cockpit.pending_destructive` row. The destructive-tool list is
narrow and code-defined (`bss_orchestrator.safety.DESTRUCTIVE_TOOLS`):
`subscription.terminate`, `payment.remove_method`,
`customer.close`, `customer.remove_contact_medium`, `case.close`,
`ticket.cancel`, `order.cancel`, `provisioning.set_fault_injection`,
plus a couple of admin-shaped helpers. Additive operations (VAS
purchase, KYC attest, plan-change schedule, case open, etc.) run
without the bracket — they're recoverable.

**Why:** The cockpit's only review surface, after staff auth
retired, is the operator's eye on the propose payload. The LLM
proposes wrong things sometimes; even a trusted operator wants a
"are you sure" beat for irreversible ops. Mirrors the customer-side
step-up pattern (v0.10) shape, but the trigger is operator
acknowledgement rather than OTP.

**Alternatives rejected:**

- **Always run with `allow_destructive=True`.** Rejected: removes
  the only review surface; an LLM hallucinating a `terminate` call
  costs the customer a number.
- **Always run with `allow_destructive=False`.** Rejected: the
  cockpit becomes useless for legitimate ops.
- **Per-action policy table.** Rejected: scope creep; the small
  code-defined list is enough for v0.13 and easier to audit.

**Consequences:** Adding a destructive tool means adding to
`DESTRUCTIVE_TOOLS` in `bss_orchestrator/safety.py`. The
`_DESTRUCTIVE_PREFIXES` lists in the REPL and cockpit route
mirror this for the propose-detection side; drift between the two
is a doctrine bug to catch by code review (no greppable test, since
the lists serve different purposes — one filters tools, the other
detects propose intent).


## 2026-05-02 — v0.14.0 Per-domain adapter Protocols, no broker container

**Context:** v0.14 begins replacing simulated externals (mock card
tokenizer, logging email, prebaked KYC, simulator-backed eSIM) with
real providers. The integration architecture had to land before
ResendEmailAdapter shipped because v0.15 (Didit) and v0.16 (Stripe)
inherit it.

**Decision:** Per-domain adapter Protocols, no `bss-providers`
mega-package, no integration-broker container. Each domain's
adapter lives where its consumer lives — `EmailAdapter` in
`packages/bss-portal-auth` (existing), future `KycVerificationAdapter`
in `portals/self-serve/.../kyc/` (v0.15), future `TokenizerAdapter`
in `services/payment/app/domain/` (v0.16). One small new package,
`packages/bss-webhooks/`, owns only genuinely cross-cutting concerns:
HMAC signature verification (svix/stripe/didit_hmac), idempotency
keys, persistence stores for the new `integrations` schema, and
per-provider redaction.

**Why:** The four domains have fundamentally different shapes —
sync charge (payment) vs fire-and-forget side effect (email) vs
async order with eventual consistency (eSIM) vs signed-attestation
receipt (KYC). A unified `Provider.execute()` API forces lowest-
common-denominator and erases information the consumer needs. The
existing `EmailAdapter` Protocol pattern at
`packages/bss-portal-auth/bss_portal_auth/email.py:32-39` is the
gold standard already shipped — replicate it per domain rather than
reinvent.

**Alternatives rejected:**

- **Single `bss-providers` package** with all Protocols. Forces a
  shared API surface that doesn't match any domain's natural shape.
- **`services/integration-broker/` container** wrapping every SDK
  behind one HTTP API. Adds ~200MB container, ~5-15ms hop on every
  call, and becomes the single point of failure that has to know
  every provider's quirks. Service mesh without a service mesh.

**Consequences:** Adding a new provider means a new adapter file in
the consumer's package, an entry in `select_*()`, and tests. No
package-level coordination. The shared `bss-webhooks` substrate
is built v0.14-complete (all three signature schemes, even though
only svix has a v0.14 consumer) so v0.16 isn't touching shared
HMAC code under payment-scope pressure.

## 2026-05-02 — v0.14.0 BSS_<DOMAIN>_PROVIDER env naming convention

**Context:** v0.8 shipped `BSS_PORTAL_EMAIL_ADAPTER` for the
LoggingEmailAdapter / NoopEmailAdapter / SmtpEmailAdapter selector.
v0.14 needed to name three new envs (Resend) consistently with
future v0.15 (Didit) and v0.16 (Stripe) prompts so a future provider
addition doesn't rename existing vars.

**Decision:** `BSS_<DOMAIN>_PROVIDER=<name>` selects the adapter;
secrets land at `BSS_<DOMAIN>_<NAME>_<KEY>`. Examples:

* `BSS_PORTAL_EMAIL_PROVIDER=resend` →
  `BSS_PORTAL_EMAIL_RESEND_API_KEY`,
  `BSS_PORTAL_EMAIL_RESEND_WEBHOOK_SECRET`,
  `BSS_PORTAL_EMAIL_FROM`.
* (v0.15 anticipated) `BSS_PORTAL_KYC_PROVIDER=didit` →
  `BSS_PORTAL_KYC_DIDIT_API_KEY`, etc.
* (v0.16 anticipated) `BSS_PAYMENT_PROVIDER=stripe` →
  `BSS_PAYMENT_STRIPE_API_KEY`, etc.

The double segment lets a future `BSS_PAYMENT_PROVIDER=adyen` add
`BSS_PAYMENT_ADYEN_API_KEY` without renaming the Stripe vars.

**Backwards compat:** `BSS_PORTAL_EMAIL_ADAPTER` (v0.8 name) is read
as a fallback by `bss_portal_auth.email.resolve_provider_name`,
emitting a `DeprecationWarning` on use. Removed in v0.16.

**Alternatives rejected:**

- **Keep `BSS_PORTAL_EMAIL_ADAPTER` and don't rename.** Rejected:
  "adapter" is a Python pattern name, not a deployment concept.
  Operators reading `.env` see "provider" and know it means a real
  external service.
- **Use `BSS_RESEND_API_KEY` (no domain prefix).** Rejected:
  ambiguous when two domains use the same provider (e.g. if Resend
  ever ships a different surface for marketing campaigns).

**Consequences:** Every adapter selector in v0.14+ follows the
pattern. `bss onboard` prompts and writes the long names. The grep
guard `rg 'os\.environ.*BSS_.*_PROVIDER'` catches per-request env
reads (forbidden — load once at startup).

## 2026-05-02 — v0.14.0 external_ref envelope on audit.domain_event

**Context:** The forensic question "this customer signed up but their
welcome email never arrived — what happened?" requires joining the
BSS-side domain event (e.g. `portal_auth.identity.created`) with
the provider call (Resend `msg_*`) with the inbound webhook
(`email.delivered` / `email.bounced`). v0.14 didn't want to add a
foreign-key column to `audit.domain_event` because that table is
hot, append-only, and pre-existing rows shouldn't backfill.

**Decision:** `audit.domain_event.payload` JSONB gains an optional
`external_ref` envelope — `{provider, operation, id,
idempotency_key}` — on rows that originated from a provider call.
Forensic join: `audit.domain_event.payload->'external_ref'->>'id'
↔ integrations.external_call.provider_call_id`. No schema change.

**Alternatives rejected:**

- **New columns on `audit.domain_event`.** Rejected: requires a
  migration on a large hot table; pre-v0.14 rows have no value to
  backfill.
- **Separate `audit.domain_event_external_ref` join table.** Rejected:
  one extra row per provider-mediated event doubles write volume on
  the hot path for negligible query benefit. JSONB query path is
  fast enough.

**Consequences:** Adapter callers who write to `audit.domain_event`
include `external_ref` in the payload when applicable. v0.14 doesn't
mandate this on all sites; the Resend adapter records to structlog
only (sync adapter Protocol doesn't have an async session in scope).
v0.15+ async adapters will tighten this to "every external call
emits external_ref-enriched audit event AND a row in
integrations.external_call."
