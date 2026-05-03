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
- **eSIM redownload re-arm flow.** Real GSMA SGP.22 redownload requires the operator to call SM-DP+ to release / re-arm an `Installed` profile (or mint a fresh activation code bound to a new ICCID) before a new device can scan the LPA. v0.10's `/esim/<subscription_id>` is a read-only re-display of the activation code minted at signup — no SM-DP+ rearm, no device-binding semantics. SM-DP+ is simulated, so there is nothing to re-arm yet. The real flow ships post-v0.1 as a SOM task (`ESIM_PROFILE_REARM`) once the SM-DP+ adapter is real. See DECISIONS 2026-04-27.
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

> **(v0.13) No staff-side auth.** The cockpit runs single-operator-by-design behind a secure perimeter. `actor` for cockpit turns comes from `.bss-cli/settings.toml` — descriptive, not verified. The Phase-12 OAuth/RBAC ambition for staff is **retired**, not deferred. Customer-side auth (v0.8–v0.10 portal session + step-up + named tokens at the perimeter) is unchanged. See DECISIONS 2026-05-01 for the rationale.

v0.3 introduces the smallest possible auth story: a single shared API token that gates every BSS service's HTTP surface. v0.1 and v0.2 had no authentication at all. v0.9 splits that into named tokens per external-facing surface. Customer-side auth (v0.8 portal session, v0.10 step-up) sits in front of the self-serve portal. Staff side runs behind a secure perimeter without a login wall — see the v0.13 cockpit doctrine below.

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

If a future operator-side identity story does ship, the BSSApiTokenMiddleware swap (token → JWT validator) is the change per service. `auth_context.py` then reads claims from the JWT instead of headers. Business logic stays untouched. As of v0.13 there is no concrete ship plan — staff trust is perimeter-based.

### What v0.9 ships (named tokens at the BSS perimeter)

v0.9 splits the v0.3 single-token model. Each external-facing surface carries its own named identity at the perimeter; the receiving services derive `service_identity` from validated token map lookup. `BSS_PORTAL_SELF_SERVE_API_TOKEN` is the self-serve portal's token (identity `"portal_self_serve"`); `BSS_OPERATOR_COCKPIT_API_TOKEN` (v0.13) is the cockpit's token (identity `"operator_cockpit"`); `BSS_API_TOKEN` remains the default identity used by the orchestrator. The named-token mechanism stands; rotating any one surface's credential is independent of the others.

- **`bss_middleware.TokenMap`** loads at startup from any `BSS_*_API_TOKEN` env var. Identity is derived from the env-var name (`BSS_PORTAL_SELF_SERVE_API_TOKEN` → `"portal_self_serve"`, `BSS_PARTNER_ACME_API_TOKEN` → `"partner_acme"`, etc.). Tokens stored hashed (HMAC-SHA-256, fixed salt) so the in-memory map is safe to log at debug level.
- **`BSSApiTokenMiddleware` upgraded** to validate against the map and attach `service_identity` to ASGI scope on hit. v0.3 single-token deployments work unchanged (resolve to identity `"default"`).
- **`bss_clients.NamedTokenAuthProvider`** for outbound calls from external-facing surfaces. The self-serve portal builds its `bss-clients` bundle with this provider against `BSS_PORTAL_SELF_SERVE_API_TOKEN` (with `BSS_API_TOKEN` fallback for staged rollout).
- **`auth_context.AuthContext.service_identity`** field flows through every service. RequestIdMiddleware reads `scope["service_identity"]` (set by perimeter token validation) and stamps it. `audit.domain_event.service_identity` column captures it on every write. structlog and OTel server spans carry it too. `bss trace` swimlane surfaces it as a per-span column.
- **`astream_once(service_identity=...)`** parameter added (used by v0.11 portal chat). Sets a per-Context `X-BSS-API-Token` override so a single agent run can attribute its tool calls to a different surface than the orchestrator's default identity.

### What v0.8 ships (self-serve portal only)

v0.8 puts a login wall in front of the self-serve portal. The CSR (operator) surface is **not** auth-gated — v0.13 retired the v0.5 stub-login pattern entirely; the cockpit runs single-operator-by-design behind a secure perimeter (see "v0.13 cockpit doctrine" below).

- **`packages/bss-portal-auth/`** — email-based identity. Public API: `start_email_login`, `verify_email_login`, `current_session`, `rotate_if_due`, `revoke_session`, `link_to_customer`, `start_step_up`, `verify_step_up`, `consume_step_up_token`. Sessions are server-side; cookies carry the session id only. Step-up auth is required for sensitive actions (defined in v0.10+ as scope expands). Per-principal OAuth2/JWT remains a Phase 12 concern.
- **`portal_auth` schema** (migration 0008): `identity`, `login_token`, `session`, `login_attempt`. Tokens stored as HMAC-SHA-256 with the server pepper from `BSS_PORTAL_TOKEN_PEPPER` env. Comparison is timing-safe (`hmac.compare_digest`). Pepper validated at portal startup (`validate_pepper_present`).
- **Email delivery** is pluggable. v0.8 ships `LoggingEmailAdapter` (writes OTPs + magic links to `BSS_PORTAL_DEV_MAILBOX_PATH`) and `NoopEmailAdapter` (tests). `SmtpEmailAdapter` is reserved for v1.0.
- **`PortalSessionMiddleware`** on self-serve resolves the cookie, attaches `request.state.session`/`identity`/`customer_id`, and rotates session ids past TTL/2.
- **Public-route allowlist** (`bss_self_serve.security`): `/welcome`, `/plans`, `/auth/*`, `/static/*`, `/portal-ui/static/*`. Adding a new public route requires an entry in the allowlist plus a test.
- **Account-first signup funnel** (`/signup/{plan}` and friends are gated on `requires_verified_email`). The agent stream calls `link_to_customer` the moment `customer.create` returns a CUST-* id, atomically binding the verified identity to the customer record.

### v0.13 cockpit doctrine (operator-side, supersedes the prior staff-auth ambition)

- **No login.** No `OperatorSessionStore`. No middleware-level staff-auth gate. The CLI REPL (`bss`) is the canonical operator cockpit; the browser veneer at `localhost:9002/cockpit/<id>` is a thin mirror over the same Postgres-backed `cockpit.session` / `cockpit.message` / `cockpit.pending_destructive` tables.
- **`actor` from `.bss-cli/settings.toml`.** Descriptive, not verified. Cockpit-driven downstream calls stamp `audit.domain_event.actor=<settings.actor>` + `service_identity="operator_cockpit"` + `channel="cli"|"portal-csr"`. Forensic per-model attribution still lives in `audit.domain_event.actor` for the LLM-driven side (`llm-<model-slug>`).
- **`OPERATOR.md` as operator-editable persona.** Prepended verbatim to every cockpit system prompt by `bss_cockpit.build_cockpit_prompt`. House rules + tone + escalation guidance. Hot-reloaded on mtime; no process restart required.
- **`/confirm` for destructive ops.** Propose → operator types `/confirm` (REPL) or clicks the button (browser) → next turn runs `allow_destructive=True`. `cockpit.pending_destructive` row tracks the in-flight propose. The destructive-tool list is small and code-defined (`bss_orchestrator.safety.DESTRUCTIVE_TOOLS`).
- **`operator_cockpit` tool profile = full registry minus `*.mine` wrappers.** Coverage assertion, not restriction. Adding a new tool requires explicit profile inclusion; startup `validate_profiles()` enforces. No prompt-injection containment seam needed (the operator IS the trust principal).
- **Phase-12 staff auth is retired**, not deferred. Customer-side OAuth/Singpass remains a v1.0 concern via the channel layer, not BSS-CLI.

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
- **(v0.7+) Subscription price is snapshotted at order time.** Renewal charges the snapshot, not the catalog. Catalog price changes affect new orders only; existing subscriptions migrate via an explicit operator-initiated flow (`subscription.migrate_to_new_price`) with regulatory notice.
- **(v0.12+) Chat is one modality of access, not a privileged path.** The same tool surface, under the same server-side policies, viewed through a tighter prompt-visible window. Customer chat sees the `customer_self_serve` profile (ownership-bound `*.mine` wrappers + public catalog reads); CSR/CLI/scenario callers keep full surface access. If the chat ever has a tool the customer's direct UI doesn't, that's a doctrine bug.
- **(v0.12+) The five escalation categories are not negotiable.** Fraud, billing dispute, regulator complaint, identity recovery, bereavement — all are `case.open_for_me` calls with no AI-side resolution attempt. The `EscalationCategory` Literal, the soak corpus, and the customer-chat system prompt encode the same list. Adding a sixth is a doctrine decision, not a scope decision.
- **(v0.13+) The REPL is the canonical operator cockpit.** The browser at `localhost:9002/cockpit/<id>` is a thin veneer over the same `Conversation` store. Slash-command parity is a doctrine target — if the REPL has `/focus` and the browser has no equivalent button, that's a doctrine bug to fix in the next sprint.
- **(v0.13+) Operator persona lives in `OPERATOR.md`.** Prepended verbatim to every cockpit system prompt. House rules are operator-editable; the cockpit's safety contract (propose-then-confirm, escalation list, ASCII rules) is code-defined in `bss_cockpit.prompts._COCKPIT_INVARIANTS`. An operator who wants to weaken the contract has to edit code, not a markdown file.

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
- **LLM gateway:** OpenRouter via the openai SDK (no LiteLLM hop) → `google/gemma-4-26b-a4b-it` (v0.10.0+; previously MiMo v2 Flash, swapped due to tool-call latency regression — see DECISIONS 2026-04-27)
- **Database:** PostgreSQL 16, **single instance**, schema-per-domain (see ARCHITECTURE.md for future split path)
- **Vector DB (post-v0.1):** pgvector extension on the same Postgres instance (schema `knowledge`)
- **Reporting:** Metabase
- **Logging:** structlog (JSON)
- **Tracing (v0.2):** OpenTelemetry SDK + auto-instrumentors (FastAPI, HTTPX, AsyncPG, AioPika); OTLP/HTTP export to Jaeger
- **Auth (v0.3):** Shared `BSS_API_TOKEN` middleware (`packages/bss-middleware`) on every BSS service; `TokenAuthProvider` on every outbound client. Per-principal OAuth2 / JWT is Phase 12.
- **Portals (v0.4-v0.5):** FastAPI + Jinja + HTMX, server-rendered HTML, vendored `htmx.min.js` + `htmx-sse.js`. No React/Vue/Svelte, no bundler, no npm. Shared widgets in `packages/bss-portal-ui`.
- **Internal packages:** `bss-clients`, `bss-clock`, `bss-cockpit` (v0.13), `bss-events`, `bss-middleware`, `bss-telemetry`, `bss-portal-ui`, `bss-portal-auth`, `bss-admin`, `bss-models`, `bss-seed` — all under `packages/` as `uv` workspace members.
- **Testing:** pytest + pytest-asyncio + httpx AsyncClient
- **Linting:** ruff + black + mypy
- **Container:** multi-stage Dockerfiles, non-root users, distroless final stage where practical

## Deployment model

BSS-CLI ships as **9 service containers + 2 portal containers** plus four optional infrastructure containers (Postgres, RabbitMQ, Metabase, Jaeger). Billing was deferred to v0.2 — port 8009 reserved (`DECISIONS.md` 2026-04-13). Self-serve portal on 9001 (v0.4); operator cockpit (browser veneer over the v0.13 cockpit Conversation store) on 9002. The CLI REPL (`bss`) is the canonical cockpit surface; the browser is the same conversation viewed in HTML. Deployers with existing Postgres/RabbitMQ/Jaeger bring their own infra; the all-in-one profile brings up everything for development and demo.

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
- **(v0.4–v0.10 / signup + chat — historical)** Through v0.10 the signup funnel and the chat surface both went through the orchestrator via `agent_bridge.*` → `astream_once`. v0.11 retired this for signup; see the `(v0.11+ / chat only)` entry below for the active doctrine.
- **(v0.10+ / authenticated post-login customer self-serve) Routes that require a verified linked-customer session may write directly via `bss-clients`.** The customer's principal is bound from `request.state.customer_id`; policies enforce ownership server-side; step-up auth gates sensitive writes. Greppable: `rg 'astream_once' portals/self-serve/bss_self_serve/routes/` must match only the chat route (post-v0.11; signup is no longer orchestrator-mediated).
- **(v0.11+ / chat only) Only the chat surface goes through the orchestrator.** The signup funnel writes directly via `bss-clients` from route handlers, with the same shape as v0.10 post-login routes: one route → one BSS write, ownership-bound where applicable, audited where applicable. The v0.4 agent-log demo artifact is retired from the primary signup path; the educational story moves to the LLM heroes (`llm_troubleshoot_blocked_subscription`, `portal_csr_blocked_diagnosis`) and the chat surface (still orchestrator-mediated; v0.12 narrows it further with a per-customer scoped tool profile). The git tag `v0.10.0` preserves the agent-log signup demo if anyone needs it.
- **(v0.5+) Don't attribute agent actions to `channel=llm` when the operator is human.** Pass `actor=<operator_id>` to `astream_once` so the interaction log answers "who asked", not "what executed". Forensic per-model attribution lives in `audit.domain_event`.
- **(v0.4+) Don't reach for React/Vue/Svelte to make a portal page snappier.** HTMX + SSE handles streaming-tool-call-log + auto-refresh patterns with less code, no bundler, no npm.
- **(v0.5+) Don't call `datetime.now()` / `datetime.utcnow()` in business-logic paths.** Use `bss_clock.now()`. The grep guard (`make doctrine-check`) added in v0.6 enforces it.
- **(v0.7+) Don't call catalog active-price queries at renewal time — read the snapshot off the subscription.** Catalog at renewal silently changes prices on existing customers and breaks the snapshot doctrine.
- **(v0.7+) Don't schedule a plan change as terminate-and-recreate.** Pending fields + renewal-time pivot is the only correct path. Terminate-recreate loses VAS top-ups, mis-attributes voluntary churn in the audit log, and leaves the customer without a line.
- **(v0.8+) Don't accept a user-controllable `customer_id` in any post-login route handler.** Read it from `request.state.customer_id`, which is bound from the verified session by `PortalSessionMiddleware`. Trusting form/query input here is how account-takeover slips in.
- **(v0.8+) Don't store login OTPs or magic-link tokens in plaintext.** HMAC-SHA-256 with the server pepper, timing-safe compare. The `bss_portal_auth` helpers are the only path. Greppable: `rg 'log\.(info|debug|warning).*(otp|magic_link|token)' packages/bss-portal-auth/` must stay empty.
- **(v0.8+) Don't route public marketing pages through session-required middleware.** `/welcome` and `/plans` are explicitly public; `/auth/*` is the gate; everything else gates on session via the deps in `bss_self_serve.security`. Adding a new public route requires both an allowlist entry and a test.
- **(v0.8+) Don't read cookies from a portal route handler.** `PortalSessionMiddleware` is the only path that touches the cookie header off the ASGI scope; route handlers consume `request.state.session` / `request.state.identity` instead. Greppable: `rg 'request\.cookies\[' portals/self-serve/` must stay empty.
- **(v0.9+) Don't trust an `X-BSS-Service-Identity` (or any sibling) header.** The resolved `service_identity` comes from token validation against the `TokenMap`, never from a separate caller-asserted header. A header is forgeable; the validated map is not. Greppable: `rg 'X-BSS-Service-Identity' --type py` must stay empty.
- **(v0.9+) Don't share a named token across surfaces.** Each external-facing surface (portal, partner client) gets its own `BSS_<NAME>_API_TOKEN`. Sharing one token defeats the blast-radius reduction that named tokens exist to provide — a leaked credential rotates one surface, not the union of every surface that happened to use it.
- **(v0.9+) Don't read `os.environ` for tokens at request time.** Load once at startup, cache, rotate by restart. Per-request env reads are slow and obscure the contract that tokens are immutable across the process lifetime. Greppable: `rg 'os\.environ.*BSS_.*API_TOKEN' --glob '!**/api_token.py' --glob '!**/auth.py' --glob '!**/conftest.py' --glob '!**/test_*.py' --glob '!**/session.py'` must stay empty.
- **(v0.10+) Don't accept user-controllable `customer_id` / `subscription_id` / `service_id` / `payment_method_id` in any post-login route handler.** `customer_id` is read from `request.state.customer_id` (bound from the verified session); every other resource id passed by the customer is checked against that principal via a policy (`check_subscription_owned_by`, `check_service_owned_by`, `check_payment_method_owned_by`) before any read or write. Cross-customer attempts return 403 with a structured error. Greppable: `rg 'customer_id\s*=\s*(form|body|query|path|request\.json)' portals/self-serve/bss_self_serve/routes/` must stay empty.
- **(v0.10+) Don't compose multiple post-login writes in a single route handler.** Each route is one `bss-clients` write call (or zero). Compositions ("do A then B; if B fails compensate A") belong in the orchestrator or in a service-side composite operation — never in a route handler, where there is no rollback story. The single exception is the cross-schema email-change flow, which uses an explicit transaction spanning `crm` + `portal_auth` (same Postgres) and is documented as such.
- **(v0.10+) Don't bypass step-up auth on a sensitive write.** The list (VAS purchase, COF add/remove/set-default, subscription terminate, email change, phone update, address update, plan-change schedule, plan-change cancel) lives as `SENSITIVE_ACTION_LABELS` in `portals/self-serve/bss_self_serve/security.py` and is enforced via the `requires_step_up(label)` dependency, not by convention. A test asserts every `requires_step_up(...)` call site uses a label from this set, and that every label appears in at least one call site. Adding a new sensitive route requires adding its label to the catalogue.
- **(v0.12+) Don't accept `customer_id` (or any owner-bound id like `customer_email`, `msisdn`) as a parameter on a `*.mine` / `*_for_me` tool.** Bind from `auth_context.current().actor`. The signature simply omits these. Greppable + startup self-check (`tools/_profiles.py:validate_profiles`) enforces. The wrappers are the prompt-injection containment layer; a parameter would let a prompt-injected LLM target another customer even though server-side policies still block the cross-customer attempt.
- **(v0.12+) Don't extend the `customer_self_serve` tool profile without a security review.** Each new tool widens the chat's autonomous reach. The list in `orchestrator/bss_orchestrator/tools/_profiles.py` is the source of truth; every entry must have a matching `OWNERSHIP_PATHS` entry (use `[]` when the tool's response carries no customer-bound fields). The runbook section "Adding a tool to the customer_self_serve profile" carries the checklist.
- **(v0.13+) Don't reach for OAuth/RBAC for staff.** The cockpit is single-operator-by-design behind a secure perimeter. Audit attribution comes from `settings.toml`; trust is perimeter-based. The Phase-12 staff-auth ambition is retired (DECISIONS 2026-05-01). If a future ops setup actually needs multi-operator separation, the path is multi-tenant carve-out (one cockpit container per operator namespace), not a login wall.
- **(v0.13+) Don't read `OPERATOR.md` or `settings.toml` outside `bss_cockpit.config`.** Hot-reload (mtime caching + `last_loaded_at` snapshot) is the contract. Direct file reads bypass the cache and risk drift between the REPL and the browser surface.
- **(v0.13+) Don't bypass `/confirm` for destructive actions in the cockpit chat.** The `cockpit.pending_destructive` row is the contract; the system prompt instructs propose-then-confirm; only consuming the row flips `allow_destructive=True` for the next turn. Bypassing is a doctrine bug — even an LLM the operator trusts proposes wrong things, and the operator's eye on the propose payload is the only review surface left after staff auth retired.
- **(v0.13+) Don't add a Conversation store to a service.** Cockpit conversations live in the `cockpit` schema owned by `bss-cockpit`; portals + REPL consume, neither reimplements. Customer chat keeps its own per-customer conversation store (different scoping concern, different lifecycle); future convergence is a post-v0.13 question.
- **(v0.13+) Don't accept user-controllable `session_id` outside the cockpit routes.** The REPL's `--session SES-...` reads from CLI argv (operator-typed); the browser's `/cockpit/<id>` reads from URL path. Both resolve through `Conversation.resume()`, which raises `LookupError` on a missing id. There's no need for ownership scoping (the cockpit is single-operator-by-design), but every other route must not take a session id off external input.
- **(v0.13+) Don't store secrets in `settings.toml`.** `BSS_*_API_TOKEN`, DB URL, OpenRouter key — those stay in `.env`. `settings.toml` is non-secret operator preference (audit name, model, ports, etc.). The greppable rule: anything that would burn the perimeter if leaked stays in env.
- **(v0.12+) Don't let the chat surface escape its scope.** The chat route is the only orchestrator-mediated route in self-serve (greppable: `rg 'astream_once' portals/self-serve/bss_self_serve/routes/` must match `chat.py` only). Cap-trip → templated SSE response, never a raw error. `AgentOwnershipViolation` from the trip-wire → generic safety reply, no leaked tool name. The OpenRouter API key never leaves the orchestrator process.
- **(v0.14+) Don't add a unified `Provider.execute()` API.** Per-domain adapter Protocols only. Email lives in `bss-portal-auth`, future KYC in the portal, future payment in `services/payment`. The four domains have genuinely different shapes; a unified API forces lowest-common-denominator and erases information consumers need.
- **(v0.14+) Don't put webhook receivers behind `BSSApiTokenMiddleware`.** Webhooks authenticate via provider signature (svix/stripe/didit_hmac) inside the route handler. The BSS perimeter token would prevent Resend/Stripe/Didit from ever reaching us. Greppable: `rg 'WEBHOOK_EXEMPT_PATHS' packages/bss-middleware/` must list `/webhooks/`.
- **(v0.14+) Don't log raw provider responses.** Use `bss_webhooks.redaction.redact_provider_payload()` before persisting or logging. Resend leaks recipient address, Stripe leaks customer email + billing details, Didit leaks document numbers. Greppable: `rg 'log\.(info|debug).*\b(stripe|didit|resend)\.(response|body)' --type py` must stay empty.
- **(v0.14+) Don't store provider config in DB.** v0.14–v0.16 are `.env` only. `bss onboard` writes `.env` atomically; tenant-scoped multi-tenant config is post-v0.16 work. Premature DB config creates a "what's the source of truth" question without the multi-tenant value to justify it.
- **(v0.14+) Don't silently fall back to a mock when prod creds are unset.** `select_*` functions raise `RuntimeError` with a specific missing-var message; never return `MockAdapter`. The fail-fast is the doctrine — silent downgrade hides misconfig until a customer-facing failure.
- **(v0.14+) Don't accept user-controllable provider name on a route.** Provider is resolved from env at startup, attached to `app.state`. A POST body field that selects a provider is an arbitrary-tool primitive. Same logic as v0.9's "don't trust `X-BSS-Service-Identity`".
- **(v0.14+) Don't read provider env vars at request time.** Load once at startup via `Settings()` / `select_*`, cache on `app.state`. Per-request `os.environ.get("BSS_*_API_KEY")` reads are slow, obscure the contract that tokens are immutable across the process lifetime, and break the "rotate by restart" semantics. Greppable: `rg 'os\.environ.*BSS_PORTAL_EMAIL' --glob '!**/conftest.py' --glob '!**/test_*.py' --glob '!**/onboard.py'` must stay empty.
- **(v0.15+) Don't add a `services/kyc/` container.** KYC verification is channel-layer; BSS only verifies signed attestations. The portal IS the channel layer in this deployment. Adding a service inverts the doctrine. Greppable: `find services -type d -name 'kyc'` must stay empty.
- **(v0.15+) Don't pass raw KYC document numbers across the BSS boundary.** Reduce to `document_number_last4` (PDPA-aligned partial display, e.g. `796B` for NRIC `S8369796B`) plus `document_number_hash` (SHA-256, domain-separated as `sha256(number|country|provider)`) inside `DiditKycAdapter.fetch_attestation` before returning. Names, addresses, biometric URLs, MRZ data, parsed-address breakdown, and liveness scores are explicitly NOT carried on the `KycAttestation` — only the verification receipt. Greppable: `rg '\b(first_name|last_name|full_name|address|place_of_birth|portrait_image|front_image|back_image|reference_image|video_url|mrz)\b' services/crm/app/ portals/self-serve/bss_self_serve/kyc/didit.py` must only match the redaction call site (`_build_attestation`), never a write or assignment.
- **(v0.15+) Don't trust a Didit attestation without a corroborating verified-webhook row.** The `GET /v2/session/{id}/decision/` API returns plain JSON over TLS — forgeable by a compromised portal. Trust anchor is the HMAC-signed webhook recorded in `integrations.kyc_webhook_corroboration`. Policy `check_attestation_signature` rejects (`rule=kyc.attestation.uncorroborated`) any `provider="didit"` attestation whose `corroboration_id` doesn't resolve to a fresh `Approved` row.
- **(v0.15+) Don't silently fall back to a different KYC provider when the active one caps out.** The Didit free-tier (500/month) is a binding constraint; on exhaustion, `DiditKycAdapter.initiate` raises `KycCapExhausted`, the customer sees a templated retry page, ops gets a `kyc.cap_exhausted` event. A best-effort prebaked attestation when Didit ran out of calls is an attestation the regulator will not honor.
- **(v0.15+) Don't accept attestations with `provider="prebaked"` (or legacy `myinfo`) in production unless `BSS_KYC_ALLOW_PREBAKED=true` is set explicitly.** The default is reject when `BSS_ENV=production`. Outside production the default is accept (so the v0.12 14-day soak corpus and hero scenarios keep working).
- **(v0.15+) Don't enable `BSS_KYC_ALLOW_DOC_REUSE=true` in production.** This sandbox-testing affordance bypasses the `customer.attest_kyc.document_hash_unique_per_tenant` policy so the same document hash can re-link to the latest customer (the prior identity row is dropped and replaced). The flag exists because Didit sandbox returns a stable test NRIC for every verification — without it, every second-and-later sandbox signup trips the uniqueness check. In production, where each verified person has a globally unique document number by definition, the flag's job is to default false and stay there.
- **(v0.15+) Don't pre-build a generic JWKS validator for Didit.** Didit's decision API has no JWS (probed 2026-05-02). The earlier draft of `phases/V0_15_0.md` called for a `_jwks_cache.py`; that helper is intentionally absent. If a future Didit API tier ships signed payloads, reintroduce the verifier *then*. Greppable: `rg 'BSS_PORTAL_KYC_DIDIT_JWKS_URL' --type py` must stay empty.
- **(v0.15+) Don't fail startup on `BSS_ESIM_PROVIDER=onbglobal` or `=esim_access`.** Fail on first use with the v0.16+ pointer message. `select_esim_provider` returns the stub at startup and the stub raises `NotImplementedError` only when the worker actually tries to call it.
- **(v0.16+) Don't render server-side card-number inputs when `BSS_PAYMENT_PROVIDER=stripe` and `BSS_ENV=production`.** Track 2 startup template scan refuses to boot. PCI scope (SAQ A) depends on this. Server-side `tokenize` raises `NotImplementedError` from `StripeTokenizerAdapter` because anyone calling it is making a security mistake. Greppable in production deployments: `rg 'name="card_number"' portals/self-serve/.../templates/` must stay empty.
- **(v0.16+) Don't auto-open a case on `charge.dispute.created`.** Record-only via `payment.dispute_opened` event for the cockpit to surface. Motto #1: no dunning, no collections, no auto-action on payment-collection-adjacent events. The operator opens the case if they choose. The version of BSS-CLI that auto-acts on chargebacks is a different product.
- **(v0.16+) Don't auto-adjust balances on out-of-band refunds.** v0.16 records `payment.refunded` with the refund amount; balance reversal is operator-initiated via existing tools. The product is bundled-prepaid; refund is an exception, not a flow.
- **(v0.16+) Don't reuse an idempotency key across user-initiated retries.** Same key only on BSS-crash-restart retries (the v1.0 path; not implemented in v0.16). v0.16 always uses `r0` (one attempt row → one key). Greppable: any code constructing `f"ATT-{x}-r0"` outside `PaymentService.charge` is wrong. See `docs/runbooks/payment-idempotency.md`.
- **(v0.16+) Don't call `mock_tokenizer.charge` directly from `payment_service.py`.** v0.16 retired that call site; all charges go through `self._tokenizer.charge(...)` (TokenizerAdapter injected via constructor). Greppable: `rg 'mock_tokenizer\.(tokenize|charge)' services/payment/app/services/` must match nothing.
- **(v0.16+) Don't switch payment providers without a documented cutover.** A `payment_method.token` minted as a mock token is unusable when Stripe is selected. Run `bss payment cutover --invalidate-mock-tokens` (proactive) or accept lazy-fail with documented customer-comms; do not flip the env var blind. The lazy-fail policy is `payment.charge.token_provider_matches_active`. See `docs/runbooks/stripe-cutover.md`.
- **(v0.16+) Don't ship the Stripe webhook receiver without diagnostic logging on `signature_invalid`.** `candidate_headers` (header keys + truncated values; secrets/tokens redacted) AND `body_preview` (first ~500 chars) on every rejection. v0.15's three Didit deliveries failed silently; the diagnostic logging was bolted on reactively in commit `a17a5c9`. v0.16 ships it from day one. Verified by `test_signature_invalid_emits_diagnostic_log` against capsys; webhook secret never appears in the log.
- **(v0.16+) Don't gate webhook reconciliation on "is this the first time we've seen this provider session."** Stripe (like Didit) emits multiple webhooks per logical state transition. The handler dedupes on `(provider, event_id)` for retries — but updates the receiving `payment_attempt` row on every webhook for a given `payment_intent_id`, last-write-wins. v0.15 commit `a649bba` documented the inverse anti-pattern (`if inserted and decision_status` meant only the FIRST webhook ever updated). Don't repeat.
- **(v0.16+) Don't treat the Stripe webhook as the primary source of truth for `payment_attempt.status`.** The synchronous `StripeTokenizerAdapter.charge` response is primary; webhooks reconcile and detect drift. A webhook saying success when the row says failed (or vice versa) emits `payment.attempt_state_drift` for ops; the row state is NOT overwritten. Spec trap #2.
- **(v0.16+) Don't enable `BSS_PAYMENT_ALLOW_TEST_CARD_REUSE=true` in production.** This sandbox-testing affordance lets the same Stripe test `pm_*` re-attach to multiple BSS customers (Stripe's `pm_card_visa` is a single token shared across many sandbox customers). `select_tokenizer` refuses the flag at startup if paired with `sk_live_*`. In production, where each customer's payment method is genuinely unique, the flag's job is to default false and stay there.

## Project meta

- **License:** Apache-2.0
- **Repo:** monorepo, `uv` workspace
- **Branching:** `main` is shippable; feature branches per phase
- **Commits:** Conventional Commits (`feat(crm): add case lifecycle`), one commit per phase minimum
- **CI:** GitHub Actions, runs linters + tests + hero scenarios on every PR (added post-Phase 10)
- **Versioning:** SemVer. v0.1.0 = first shippable demo.
