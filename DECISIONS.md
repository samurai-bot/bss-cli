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
