# CLAUDE.md — BSS-CLI Project Doctrine (v3)

> **This file is your contract.** Read it at the start of every session. Do not deviate without an explicit Phase 0 amendment from the human.

## What this project is

**BSS-CLI** is a complete, lightweight, SID-aligned, TMF-compliant Business Support System designed to run entirely from a terminal. It is LLM-native: every operation is exposed as a tool the LLM can call, and the primary UI is the CLI plus ASCII-rendered visualizations. Metabase is the only graphical surface and is reserved for analytical reporting.

It is a **reference implementation** for engineers learning telco BSS/OSS, a **deployable MVP** for a small MVNO, and a **substrate** for agentic experiments against realistic telco operations. It covers CRM (with case/ticket management), Product Catalog, Commercial Order Management (COM), Service Order Management (SOM) with a provisioning simulator, eSIM profile management, Subscription & Bundle Balance, Mediation, Rating, and Payment.

## The seven motto principles (NEVER violate)

1. **Bundled-prepaid only.** No proration. No dunning. No collections. No credit risk modeling. The product is a bundle, the customer pays upfront via card-on-file, the bundle either has remaining quota or it doesn't.
2. **Card-on-file is mandatory.** Every customer has a payment method before activation. Failed charge equals no service. There is no grace period, no retry ladder, no manual collection workflow.
3. **Block-on-exhaust.** Service stops the instant a bundle hits zero. The only paths back to active are: bundle renewal (automatic, on period boundary, charged to COF) or VAS top-up (explicit customer action, charged to COF).
4. **CLI-first, LLM-native.** Every capability is a tool the LLM can call. The terminal is the primary interface. ASCII art is the visualization language. Metabase is the only exception, reserved for analytics.
5. **TMF-compliant where it counts.** Real TMF Open API surfaces (TMF620, TMF621, TMF622, TMF629, TMF635, TMF638, TMF640, TMF641, TMF676, TMF678, TMF683). Not naming theater. Payloads match the spec.
6. **Lightweight is measurable.** The full stack runs in under 4GB RAM. Cold start under 30 seconds. p99 internal API latency under 50ms. If a change pushes us past these limits, it requires explicit justification.
7. **Write through policy, read freely.** Reads are free. Writes go through a validation layer that enforces domain invariants. There is no such thing as "raw CRUD" in BSS-CLI. The LLM cannot corrupt state even when asked to.

## Scope boundaries (what BSS-CLI is NOT)

These are things BSS-CLI deliberately does not do, and the channel layer or external systems are expected to handle:

- **eKYC.** BSS-CLI receives a signed KYC attestation from the channel layer and records it. Document capture, liveness detection, biometric matching, and government ID integration (Myinfo, DigiLocker, etc.) are channel-layer concerns.
- **Customer-facing UI.** Mobile apps, web portals, retail POS, USSD menus — all channel layer.
- **Network elements.** HLR/HSS, PCRF, OCS, SM-DP+ — simulated in v0.1, real NE adapters are an integration concern.
- **Physical SIM.** eSIM-only. No ICCID logistics, no warehousing, no courier integration.
- **CDR collection from RAN.** Mediation accepts already-parsed CDRs via API. Real CDR collection from network probes is out of scope.
- **Online Charging System (OCS).** Real-time credit authorization on Diameter Gy/Ro (PCEF quota grant, quota reservation, `Final-Unit-Indication`) is abstracted *outside* BSS-CLI. Our Mediation service is **TMF635 online mediation** — it receives one usage event at a time, enforces block-at-edge synchronously, and drives balance decrement via events. It is NOT a batch rating/mediation pipeline (no CDR file ingest, no hourly aggregation, no rerating windows), and it is NOT an OCS (no Diameter, no quota reservation protocol with the packet core). The real OCS — if one is ever wired in — lives on the network side; BSS-CLI is downstream of its decisions.
- **Tax calculation.** v0.1 uses SGD inclusive pricing. Real tax engines (Vertex, Avalara) are a post-v0.1 integration.
- **Regulatory reporting.** IMDA monthly reports, MCMC retention, etc. — extraction jobs against `audit.domain_event`, not built into services.

Documenting these non-boundaries is as important as documenting what we do build.

## Domain coverage

### CRM (lightweight but real)

- **Customer & Party.** TMF629. Customer, Individual, Contact Mediums, KYC attestation.
- **Interaction log.** TMF683. Every touchpoint logged automatically.
- **Case & Ticket management.** Custom Case aggregate + TMF621 Trouble Ticket. ServiceNow-shaped: Case parents 1..N Tickets.

### Order management (COM + SOM)

- **COM (TMF622).** Customer-facing. ProductOrder aggregate.
- **SOM (TMF641 + TMF638).** Technical. Decomposes COM orders into ServiceOrders, CFS, RFS, Resources.
- **Decomposition (v0.1):** PLAN_x → 1 CFS (MobileBroadband) → 2 RFS (Data, Voice) → {MSISDN, eSIM profile}.

### Provisioning simulator

Stands in for HLR/PCRF/OCS/SM-DP+. Configurable per-task-type fault injection. "Stuck" state for manual intervention.

### Inventory (eSIM + MSISDN)

Two pools, both managed by the Inventory domain:

- **MSISDN pool** — 1000 numbers seeded
- **eSIM profile pool** — 1000 profiles seeded, each with ICCID, IMSI, Ki-reference (NEVER raw Ki), SM-DP+ activation code

eSIM-only in v0.1. On order, SOM reserves both an MSISDN and an eSIM profile atomically. After activation, the customer receives an LPA activation code and ASCII-rendered QR code.

## The Write Policy doctrine

Every write in BSS-CLI flows through a policy layer that enforces domain invariants before the repository is touched. Router → Service → Policies → Repository → Event publisher. Always.

### Why

The LLM is powerful and will be asked to do things like "update Ck's plan" or "close all Ck's tickets". Without guardrails, an LLM can silently violate referential integrity, break state machines, orphan child records, or create impossible states. The policy layer is what lets us trust the LLM with write access.

### How

```
services/<svc>/app/
├── repositories/       # dumb CRUD over ORM
├── policies/           # invariant enforcement
├── services/           # orchestration — calls policies, not repositories
└── auth_context.py     # principal/tenant/roles (Phase 12-ready abstraction)
```

Policies validate BEFORE any write:
- **Referential invariants** — target exists, in right state, belongs to right parent
- **State machine invariants** — only legal transitions
- **Domain invariants** — e.g., "a Case cannot be closed with open Tickets"
- **Uniqueness invariants** — email, MSISDN, ICCID, external refs
- **Authorization invariants** — agent must be active, role must permit action (reads from auth_context)

On violation, a structured `PolicyViolation` is raised:

```json
{
  "code": "POLICY_VIOLATION",
  "rule": "case.close.requires_all_tickets_resolved",
  "message": "Case CASE-042 has 2 open tickets (TKT-101, TKT-103). Resolve them first.",
  "context": { "case_id": "CASE-042", "open_tickets": ["TKT-101", "TKT-103"] }
}
```

These errors flow back to the LLM as tool observations. The LLM reads the structured error and either retries with corrections or asks the user.

### No raw CRUD from CLI or LLM

Hard rule:
- CLI exposes verbs (`bss case open`), not entities (no `bss db update`)
- LLM has tools like `case.open`, not `case.update_raw`
- No escape hatch. Emergency data fixes happen via explicit admin tools which are themselves policy-gated

## Authentication & RBAC readiness

v0.3 introduces the smallest possible auth story: a single shared API token that gates every BSS service's HTTP surface. v0.1 and v0.2 had no authentication at all. Phase 12 will add per-principal OAuth2/JWT through the same `auth_context.py` seam that's been in every service since Phase 3.

### What v0.3 ships

- **`packages/bss-middleware/`** with `BSSApiTokenMiddleware` (pure ASGI). Every BSS service registers it; missing or wrong `X-BSS-API-Token` header → 401 before routing. Comparison is timing-safe (`hmac.compare_digest`). Exempt paths: exactly `/health`, `/health/ready`, `/health/live`.
- **`bss_middleware.validate_api_token_present()`** called at the top of every service's lifespan. Empty / sentinel `"changeme"` / <32-char tokens fail-fast on startup.
- **`bss_clients.TokenAuthProvider`** alongside the existing `NoAuthProvider`. Every cross-service client constructed via `orchestrator/bss_orchestrator/clients.py:get_clients()` carries the token on outbound calls.
- **`BSS_API_TOKEN` in `.env`** is the single source of truth, generated via `openssl rand -hex 32`. Rotation is restart-based (`docs/runbooks/api-token-rotation.md`).

### What's already in place from v0.1 (still applies)

- **`tenant_id` column on every table**, seeded with `'DEFAULT'`
- **`X-BSS-Actor` and `X-BSS-Channel` headers** plumbed through every HTTP call
- **Policy layer** as the single chokepoint for writes (the right place for `@requires_role`)
- **bss-clients** as the single chokepoint for service-to-service calls
- **`auth_context.py`** module in every service. v0.3 leaves it alone — RequestIdMiddleware still populates it from `X-BSS-Actor`. The principal is still the hardcoded admin.
- **Policies and tool dispatches read from `auth_context.current()`**, never hardcoded

When Phase 12 ships, the BSSApiTokenMiddleware swap (token → JWT validator) is the change per service. `auth_context.py` then reads claims from the JWT instead of headers. Business logic stays untouched.

### Phase 12 model (not in v0.1, documented for architectural intent)

- **Service-to-service:** OAuth2 client credentials, short-lived JWTs via bss-clients
- **Human-to-system:** OAuth2 Authorization Code + PKCE through an auth service (`services/auth`) backed by Keycloak/Cognito/Entra
- **8 coarse roles**: csr, senior_agent, billing_analyst, provisioning_engineer, supervisor, admin, auditor, system
- **Fine permissions** derived 1:1 from tool names
- **Resource scoping** via tenant and customer_segment claims

## Design rules

- **No retry/dunning in payment.** Fail = block. Period.
- **No proration.** Bundles renew on clean period boundaries.
- **No partial payments.** Approved in full or declined in full.
- **No credit-checking.** COF presence is the only credit signal.
- **Time is explicit.** Never call `datetime.utcnow()` in business logic. Use the `clock` service. This makes scenarios deterministic.
- **State machines, not flags.** Subscription, Order, Service, Ticket, Case — all explicit FSMs with logged transitions.
- **Events are first-class.** Every meaningful state change emits a domain event AND persists to `audit.domain_event` in the same transaction.
- **No business logic in routers.** Routers → Services → Policies → Repositories. One-way.
- **Repositories never call services.** Lowest layer, no outward dependencies.
- **Inter-service calls via HTTP for synchronous needs, RabbitMQ for asynchronous reactions.** Never shared DB access across service boundaries.
- **Each service owns its schema** in a single Postgres instance (v0.1). The schema-per-service boundary enables a later split to one Postgres per service without touching service code.

## Call patterns (HTTP vs events)

Two distinct planes:

**Synchronous HTTP (via bss-clients):** used when the caller needs an immediate answer.
- `payment.charge` (subscription needs approved/declined before activating)
- `customer.get` (CRM lookup during payment method creation)
- `catalog.get_offering` (order creation needs price)

**Asynchronous events (via RabbitMQ topic exchange `bss.events`):** used when the producer doesn't need an answer.
- `order.in_progress` (SOM reacts)
- `provisioning.task.completed` (SOM reacts)
- `service_order.completed` (COM reacts)
- `usage.rated` (Subscription decrements)

**Postgres is NOT a RabbitMQ consumer.** Each service writes directly to its own schema. The `audit.domain_event` row is written in the same DB transaction as the domain write; the RabbitMQ publish happens after commit (simplified outbox — best-effort delivery backed by the durable audit log).

## Tech stack (frozen for v0.x)

- **Language:** Python 3.12
- **Package manager:** `uv` with workspace layout
- **Web framework:** FastAPI (async everywhere)
- **ORM:** SQLAlchemy 2.0 async + asyncpg
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **State machines:** `transitions` library
- **Messaging:** RabbitMQ via `aio-pika`
- **CLI:** Typer + Rich
- **LLM orchestrator:** LangGraph
- **LLM gateway:** OpenRouter via the openai SDK (no LiteLLM hop) → MiMo v2 Flash
- **Database:** PostgreSQL 16, **single instance**, schema-per-domain (see ARCHITECTURE.md for future split path)
- **Vector DB (post-v0.1):** pgvector extension on the same Postgres instance (schema `knowledge`)
- **Reporting:** Metabase
- **Logging:** structlog (JSON)
- **Tracing (v0.2):** OpenTelemetry SDK + auto-instrumentors (FastAPI, HTTPX, AsyncPG, AioPika); OTLP/HTTP export to Jaeger
- **Auth (v0.3):** Shared `BSS_API_TOKEN` middleware (`packages/bss-middleware`) on every BSS service; `TokenAuthProvider` on every outbound client. Per-principal OAuth2 / JWT is Phase 12.
- **Portals (v0.4-v0.5):** FastAPI + Jinja + HTMX, server-rendered HTML, vendored `htmx.min.js` + `htmx-sse.js`. No React/Vue/Svelte, no bundler, no npm. Shared widgets in `packages/bss-portal-ui`.
- **Internal packages:** `bss-clients`, `bss-clock`, `bss-events`, `bss-middleware`, `bss-telemetry`, `bss-portal-ui`, `bss-admin`, `bss-models`, `bss-seed` — all under `packages/` as `uv` workspace members.
- **Testing:** pytest + pytest-asyncio + httpx AsyncClient
- **Linting:** ruff + black + mypy
- **Container:** multi-stage Dockerfiles, non-root users, distroless final stage where practical

## Deployment model

BSS-CLI ships as **9 service containers + 2 portal containers** plus four optional infrastructure containers (Postgres, RabbitMQ, Metabase, Jaeger). Billing was deferred to v0.2 — port 8009 reserved (`DECISIONS.md` 2026-04-13). Self-serve portal on 9001 (v0.4); CSR console on 9002 (v0.5). Deployers with existing Postgres/RabbitMQ/Jaeger bring their own infra; the all-in-one profile brings up everything for development and demo.

See `ARCHITECTURE.md` for the full container topology, compose profiles, and the AWS deployment path (ECS Fargate → small MVNO production → scaled MVNO).

## Naming conventions

- **Python modules:** snake_case
- **Python classes:** PascalCase
- **DB tables:** snake_case, singular (`customer`, not `customers`)
- **DB schemas:** snake_case domain name (`crm`, `catalog`, `order_mgmt`, `service_inventory`, `provisioning`, `inventory`, `knowledge`)
- **TMF payloads:** camelCase (match the spec exactly)
- **Internal DTOs:** snake_case
- **Event routing keys:** dot-separated lowercase (`subscription.exhausted`, `ticket.assigned`)
- **IDs:** prefixed strings (`CUST-001`, `ORD-014`, `SUB-007`, `CASE-042`, `TKT-101`, `SO-222`, `SVC-333`, `PTK-444`). UUIDs internally in DB are fine; the surface is always prefixed.

## Anti-patterns (never do these)

- Don't put business logic in Typer command handlers. CLI calls orchestrator or bss-clients, nothing more.
- Don't mix sync and async code paths.
- Don't catch exceptions in routers. Let middleware handle them.
- Don't log card numbers, tokens, full NRIC, full Ki values, or full ICCIDs beyond last-4. structlog has a redaction filter — use it.
- Don't add retries inside tool functions. LangGraph supervisor handles retries.
- Don't reach for a rules engine for rating. A tariff is a JSON document; rating is a pure function.
- Don't bake in channel-specific logic. BSS-CLI is channel-agnostic.
- Don't implement eKYC flows. Receive attestations, record them, enforce policies — that's it.
- Don't hardcode ports, URLs, or model names. Everything via env.
- Don't commit mid-phase. Verify first, commit after.
- Don't let Claude Code modify `CLAUDE.md`, `DATA_MODEL.md`, `ARCHITECTURE.md`, or `TOOL_SURFACE.md` without an explicit Phase 0 amendment.
- Don't bypass the policy layer. If you need to, the policy is wrong and needs amending.
- **(v0.4+) Don't write to bss-clients from a portal route handler.** Every portal write goes through the LLM orchestrator via `agent_bridge.*` → `astream_once`. Reads can go direct.
- **(v0.5+) Don't attribute agent actions to `channel=llm` when the operator is human.** Pass `actor=<operator_id>` to `astream_once` so the interaction log answers "who asked", not "what executed". Forensic per-model attribution lives in `audit.domain_event`.
- **(v0.4+) Don't reach for React/Vue/Svelte to make a portal page snappier.** HTMX + SSE handles streaming-tool-call-log + auto-refresh patterns with less code, no bundler, no npm.
- **(v0.5+) Don't call `datetime.now()` / `datetime.utcnow()` in business-logic paths.** Use `bss_clock.now()`. The grep guard (`make doctrine-check`) added in v0.6 enforces it.

## Project meta

- **License:** Apache-2.0
- **Repo:** monorepo, `uv` workspace
- **Branching:** `main` is shippable; feature branches per phase
- **Commits:** Conventional Commits (`feat(crm): add case lifecycle`), one commit per phase minimum
- **CI:** GitHub Actions, runs linters + tests + hero scenarios on every PR (added post-Phase 10)
- **Versioning:** SemVer. v0.1.0 = first shippable demo.
