# ARCHITECTURE.md — BSS-CLI (v3)

## Topology

Three callers — **CLI** (terminal-native), **self-serve portal** (public signup, port 9001), and **CSR console** (operator workbench, port 9002) — converge on the LangGraph orchestrator's tool registry. Inside, two planes connect the 9 services: **synchronous HTTP (TMF APIs)** for calls that need an immediate answer, and **asynchronous events (RabbitMQ topic exchange)** for reactions. Postgres is accessed directly by each service's own writes — the message broker is not a database pipe.

```
   ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐
   │  Self-serve UI   │  │  CSR console UI  │  │  bss (CLI + REPL)        │
   │  port 9001 (v0.4)│  │  port 9002 (v0.5)│  │  + LangGraph Orchestrator│
   └────────┬─────────┘  └─────────┬────────┘  └────────────┬────────────┘
            │                      │                        │
            │  agent_bridge.*      │  agent_bridge.*        │
            ▼                      ▼                        ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │   bss_orchestrator.session.astream_once(channel, actor=…)        │
   │   ReAct agent over the tool registry · pin allow_destructive=False│
   └──────────────────────────────────┬───────────────────────────────┘
                                      │ HTTP (TMF APIs) + bss-clients
        ┌──────┬────────┬─────────────┼────────┬────────┐
        ▼      ▼        ▼             ▼        ▼
     ┌─────┐┌─────┐ ┌─────┐       ┌─────┐┌─────┐
     │CRM* ││Pay  │ │Cat  │       │COM  ││Subs │
     │8002 ││8003 │ │8001 │       │8004 ││8006 │
     └──┬──┘└──┬──┘ └──┬──┘       └──┬──┘└──┬──┘
        │      │       │             │      │
        │      └───HTTP (e.g. Pay→CRM "customer exists?")
        │                            │
        │      ┌─────────────────────┼──────────────────────┐
        │      │         ┌─────┐┌─────┐ ┌─────┐ ┌─────┐
        │      │         │SOM  ││Med  │ │Rate ││Prov │
        │      │         │8005 ││8007 │ │8008 ││Sim  │
        │      │         └──┬──┘└──┬──┘ └──┬──┘ │8010 │
        │      │            │      │       │    └──┬──┘
        │      │            │      │       │       │
        ▼      ▼            ▼      ▼       ▼       ▼
     ═══════════════════════════════════════════════════════════
     ║         RabbitMQ — topic exchange: bss.events            ║
     ║  order.* · service_order.* · service.* · provisioning.*  ║
     ║  subscription.* · usage.* · crm.* · payment.*            ║
     ═══════════════════════════════════════════════════════════

     Each service writes directly to its own schema in ONE shared
     Postgres instance. audit.domain_event is written in the same
     transaction as the domain write; RabbitMQ publish happens
     after commit (simplified outbox). Every service exports OTel
     spans to Jaeger (v0.2+).

     ┌──────────────────────────────────────────────────┐  ┌──────────────┐
     │             PostgreSQL 16 (single instance)       │  │   Jaeger     │
     │                                                    │  │  (v0.2+)     │
     │  crm · catalog · inventory · payment · order_mgmt │  │  OTLP/HTTP   │
     │  service_inventory · provisioning · subscription  │  │  → traces UI │
     │  mediation · billing · audit · knowledge          │  └──────────────┘
     └─────────────────────────┬────────────────────────┘
                               │ read-only
                               ▼
                       ┌────────────────┐
                       │    Metabase    │
                       └────────────────┘
```

**\* CRM hosts the Inventory sub-domain** (MSISDN pool + eSIM profile pool) on port 8002 under `/inventory-api/v1/...`. Not a separate container in v0.1. See "Services" table below.

## Call patterns

### Synchronous HTTP (via bss-clients)

Used when the caller needs an immediate answer.

| Caller → Callee | Purpose |
|---|---|
| CLI/orchestrator → any service | User-facing request |
| Payment → CRM (customer_exists) | Pre-write validation |
| COM → Catalog (get_offering) | Pre-write validation |
| COM → Subscription (create on order complete) | COM waits for subscription ID |
| Subscription → Payment (charge) | Need approved/declined before activate |
| SOM → CRM Inventory (reserve_msisdn + reserve_esim) | Atomic reservation on shared CRM instance |
| CRM (close policy) → Subscription (list_for_customer) | Policy needs live answer |
| Mediation → Subscription (get_by_msisdn) | Enrichment |

### Asynchronous events (RabbitMQ)

Used when the producer doesn't need an answer and N consumers may care.

| Publisher → Routing Key | Consumers |
|---|---|
| COM → `order.in_progress` | SOM |
| SOM → `provisioning.task.created` | Provisioning-sim |
| Provisioning-sim → `provisioning.task.completed` | SOM |
| SOM → `service_order.completed` / `service_order.failed` | COM |
| COM → `order.completed` | Subscription (activation trigger) |
| Subscription → `subscription.activated` / `exhausted` / `blocked` | (future: notification, analytics) |
| Mediation → `usage.recorded` | Rating |
| Rating → `usage.rated` | Subscription |

**Event exchange:** single topic exchange `bss.events`. Consumers bind queues with routing patterns (e.g., SOM binds `order.in_progress`, `provisioning.task.completed`).

**Outbox pattern (simplified):** every service writes to `audit.domain_event` inside the same DB transaction as the domain write. After the transaction commits, a post-commit hook publishes to RabbitMQ best-effort. If RabbitMQ is down, the audit row is still present and a replay job (post-v0.1) can republish.

### Event ordering guarantees

RabbitMQ topic exchange preserves **order within a single routing key for a single consumer**. It does NOT preserve order between different routing keys, and parallel consumers on the same queue can observe events in different orders than published.

Consequences for BSS-CLI:

- **SOM receives `provisioning.task.completed` in arrival order**, not necessarily publish order. When 5 tasks complete roughly simultaneously, SOM sees them in some unspecified order. The `service.activate.requires_all_rfs_activated_and_esim_prepared` policy is the thing that enforces causality — activation only proceeds when all prerequisites are met, regardless of which arrived first.

- **Scenario `expect_event_sequence` assertions must describe causal order, not strict publish order.** When two events are concurrent (e.g., two parallel `task.started` events for different RFS), accept either ordering. The test framework polls for the sequence relation, not the exact interleaving.

- **`audit.domain_event` is ordered by `occurred_at` (post-commit timestamp).** For events published within seconds of each other from different services, the timestamps may reflect commit order, not causal order. Close reads usually agree with the mental model; races may not. When debugging a chain, trust the causal relationships (parent→child, request→response) over the absolute timestamps.

If strict ordering becomes essential for a future use case, the path forward is RabbitMQ routing by `subscription_id` (or another partition key), so all events for one subscription land on the same consumer queue. That's Phase 11+ territory; v0.1 does not need it.

## Services (9 total)

| # | Service | Port | TMF | State | Notes |
|---|---|---|---|---|---|
| 1 | catalog | 8001 | TMF620 | stateless | Read-only in v0.1 |
| 2 | crm | 8002 | TMF629 + TMF621 + TMF683 | stateful | Customer + Case + Ticket + Interaction + KYC + **Inventory sub-domain** |
| 3 | payment | 8003 | TMF676 | stateful | Mock gateway |
| 4 | com | 8004 | TMF622 | stateful FSM | Commercial Order Management |
| 5 | som | 8005 | TMF641 + TMF638 + TMF640 | stateful FSM | Service Order + decomposition |
| 6 | subscription | 8006 | custom | stateful FSM | Bundle balance, VAS, renewal |
| 7 | mediation | 8007 | TMF635 | stateful | **TMF635 online mediation.** Single-event ingest, block-at-edge, not batch. OCS is abstracted outside BSS-CLI — see "What's NOT in the architecture". |
| 8 | rating | 8008 | — | stateless | Pure rating function + consumer. Bundled-prepaid quota decrement, not per-unit billing-rate CDR rating. |
| 9 | provisioning-sim | 8010 | custom | stateful | Fake HLR/PCRF/OCS/SM-DP+, configurable failures |

Port 8009 is reserved for the v0.2 billing service — see the "Note on billing in v0.1" subsection below and `DECISIONS.md` 2026-04-13.

## Portals (channel layer, v0.4+)

A portal is a **channel** onto the BSS — a thin HTTP surface that translates a specific audience's actions (self-serve customers, CSRs, retail partners) into tool calls the LLM orchestrator runs against the 9 core services. Portals live under `portals/` in the repo, not under `services/`; each one ships as its own container on the **9xxx port range**. v0.4 shipped the self-serve portal; v0.5 adds the CSR console.

| # | Portal | Port | Audience | Writes go through… | Inbound auth |
|---|---|---|---|---|---|
| 1 | self-serve | 9001 | Prospect browsing / signing up | `agent_bridge.drive_signup` → `astream_once(channel="portal-self-serve")` | none (public signup) |
| 2 | csr | 9002 | CSR operators | `agent_bridge.ask_about_customer` → `astream_once(channel="portal-csr", actor=<op>)` | stub login (cookie); Phase 12 swaps for real OAuth |

The defining property of a portal is that **every write routes through the LLM orchestrator**. The route handler never imports `CustomerClient.create`, `OrderClient.create`, or any other mutating bss-clients method. It builds a natural-language instruction, passes it to `astream_once`, and streams the resulting events (tool call started, tool call completed, final message) back to the browser via Server-Sent Events.

- **Reads go direct.** Listing offerings, fetching a customer 360, polling order state — all direct `bss-clients` calls. LLM-mediating a pass-through read is pointless latency.
- **`X-BSS-Channel` attribution.** Every outbound call carries the portal's channel name (`portal-self-serve` or `portal-csr`) so CRM's interaction auto-log attributes the write to the right surface. The hero scenarios assert this.
- **`X-BSS-Actor` carries the human (v0.5+).** The CSR portal sets `actor=<operator_id>` on every outbound call so the interaction log shows *who* asked, not which model executed. Per-model attribution still lives in `audit.domain_event.actor` (`llm-<model-slug>`).
- **`BSS_API_TOKEN` on outbound only.** Portals' inbound HTTP surfaces are not gated by `BSSApiTokenMiddleware` (different auth stories per portal — see the table). Their outbound calls through `TokenAuthProvider` are authenticated like any other v0.3+ caller.
- **Pure server-rendered HTML + HTMX.** No React/Vue/Svelte, no bundler, no npm.

### Shared package: `packages/bss-portal-ui` (v0.5+)

The agent log widget, SSE plumbing helpers (`format_frame`, `status_html`), event-projection logic (`project`, `render_html`), base CSS (palette + layout primitives + agent log styling), and vendored HTMX (`htmx.min.js` + `htmx-sse.js`) live in a single shared package. Both portals consume it via:
- a Jinja `ChoiceLoader` that resolves portal-local templates first then falls back to the package's shared partials, and
- a `StaticFiles` mount at `/portal-ui/static/` that serves the package's CSS + JS.

Extracted in v0.5 (before the second portal was written) to prevent the agent log widget from drifting between portals — a fix landing only in self-serve when both need it would surface as a demo bug a month later. Documented in `DECISIONS.md` 2026-04-23.

The hero artifact on every portal page is the **Agent Activity** log widget — a side panel streaming the LLM's tool-call sequence live. Strip it out and the portal looks like any CRUD frontend; keep it in and the viewer can see the LLM is doing the work, tool by tool. Details in `phases/V0_4_0.md` and `phases/V0_5_0.md`.

The **Inventory sub-domain** (MSISDN pool + eSIM profile pool) lives inside the CRM service on port 8002, mounted under `/inventory-api/v1/...`. It has its own schema (`inventory`), repositories, policies, and HTTP endpoints — just no separate container. SOM and Subscription call it via `bss-clients` as if it were a distinct service. If it outgrows CRM, extraction to an 11th container is mechanical because the boundary is already enforced.

**Why 9 containers, not 10:** keeping inventory inside CRM for v0.1 reduces one network hop in the critical activation path and saves ~150MB of RAM. Domain boundary is still clean — inventory has its own schema, repositories, policies, and tool surface. See DECISIONS.md "Inventory domain hosted inside CRM service (v0.1)" for the rationale.

### Note on billing in v0.1

v0.1 ships **without a billing service**. Phase 0 planned one as service #9 (TMF678, port 8009), and the Phase 2 initial migration created the `billing` schema with two tables (`billing_account`, `customer_bill`) — but no phase actually built the service layer. v0.1.1 formally defers billing to v0.2, where it will be reintroduced as a **read-only view layer over `payment.payment_attempt`**: receipt aggregation, statement generation, TMF678 `/customerBill` endpoints. No dunning, no credit extension, no formal invoice generation — bundled-prepaid doesn't need them, since charges happen synchronously at activation / renewal / VAS purchase and are already recorded on `payment.payment_attempt`. The `billing` schema and its tables remain in the migration so v0.2 is purely additive. Port 8009 is reserved. See `DECISIONS.md` 2026-04-13 for the deferral rationale and the scope note separating the billing **service** from "billing" as CRM customer-support **vocabulary**.

## Container structure

### Default deployment: BYOI (bring your own infrastructure)

**BSS-CLI has been developed in BYOI mode from Phase 1 onwards.** The default `docker-compose.yml` contains only the 9 BSS services and assumes PostgreSQL 16 and RabbitMQ 3.13 are reachable via env-configured connection strings. Most operators already have managed Postgres (RDS, Cloud SQL) and managed MQ (Amazon MQ, CloudAMQP), so bundling an unused Postgres container would be wasteful.

```yaml
# docker-compose.yml
services:
  catalog:          { build: ./services/catalog,         env_file: .env, ports: ["8001:8000"] }
  crm:              { build: ./services/crm,             env_file: .env, ports: ["8002:8000"] }
  payment:          { build: ./services/payment,         env_file: .env, ports: ["8003:8000"] }
  com:              { build: ./services/com,             env_file: .env, ports: ["8004:8000"] }
  som:              { build: ./services/som,             env_file: .env, ports: ["8005:8000"] }
  subscription:     { build: ./services/subscription,    env_file: .env, ports: ["8006:8000"] }
  mediation:        { build: ./services/mediation,       env_file: .env, ports: ["8007:8000"] }
  rating:           { build: ./services/rating,          env_file: .env, ports: ["8008:8000"] }
  # billing: port 8009 reserved for v0.2 (see DECISIONS.md 2026-04-13)
  provisioning-sim: { build: ./services/provisioning-sim, env_file: .env, ports: ["8010:8000"] }
```

Each service reads `BSS_DB_URL` and `BSS_MQ_URL` from env. No assumptions about where Postgres or RabbitMQ live.

### Optional infra compose: all-in-one

`docker-compose.infra.yml` brings up Postgres, RabbitMQ, and Metabase in containers for operators who prefer a single-command bring-up. This is **not the primary development mode** — it exists as a bring-up convenience for new contributors and for the README quickstart.

```yaml
# docker-compose.infra.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: bss
      POSTGRES_PASSWORD: bss
      POSTGRES_DB: bss
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "bss"]
      interval: 10s

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports: ["5672:5672", "15672:15672"]
    volumes: [rabbitmq_data:/var/lib/rabbitmq]

  metabase:
    image: metabase/metabase:latest
    ports: ["3000:3000"]
    depends_on: [postgres]

volumes:
  postgres_data:
  rabbitmq_data:
```

Usage:

```bash
# BYOI (default, development mode)
docker compose up -d

# All-in-one (dev/demo, new contributor quickstart)
docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d
```

### Compose profiles for incremental bringup

For development on slow machines, profiles allow partial stacks:

```yaml
profiles:
  minimal:  [catalog, crm, payment]
  core:     [catalog, crm, payment, com, som, subscription, provisioning-sim]
  full:     [catalog, crm, payment, com, som, subscription, mediation, rating, provisioning-sim]
```

```bash
docker compose --profile core up       # Phase 3-7 development
docker compose --profile full up       # Phase 8+ and scenarios
```

### Per-service Dockerfile pattern

**Current implementation (Phase 3/4 expedient):** each service has its own `Dockerfile` that rewrites the workspace reference to a direct path before running `uv pip install`. This is a workaround for uv workspace resolution inside Docker build contexts.

```dockerfile
# services/catalog/Dockerfile (similar pattern for each service)
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv

COPY packages/ packages/
COPY services/catalog/ services/catalog/

WORKDIR /build/services/catalog
# In Docker there is no workspace root — switch source from workspace to path
RUN sed -i 's|workspace = true|path = "../../packages/bss-models"|' pyproject.toml \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python .

FROM python:3.12-slim AS runtime
RUN useradd -m -u 1000 bss && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder --chown=bss:bss /app/.venv /app/.venv
WORKDIR /app
USER bss
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "-m", "bss_catalog"]
```

**Intended long-term shape (Phase 11+ backlog):** a single shared template Dockerfile that copies the workspace root `pyproject.toml` and `uv.lock`, then uses `uv sync --package ${SERVICE}` from the workspace root. This would eliminate per-service Dockerfile duplication and let uv's workspace resolution work natively.

```dockerfile
# services/_template/Dockerfile — aspirational, not yet implemented
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/${SERVICE}/ services/${SERVICE}/
RUN uv sync --package ${SERVICE}

# ... (rest same as per-service pattern)
```

Migration tracked as a Phase 11 backlog item. See DECISIONS.md "Per-service Dockerfile with workspace sed workaround" for the full rationale.

### Footprint budget (motto #6)

Re-measured during v0.6 against the post-v0.5 stack (9 services + 2 portals + OTel SDK + middleware). BYOI numbers from `docker stats --no-stream` after 5 minutes idle; bundled numbers added to all-in-one infra (Postgres + RabbitMQ + Metabase + Jaeger). v0.1 numbers retained for reference.

| Component | v0.1 RAM | v0.6 RAM | Notes |
|---|---|---|---|
| 9 × BSS service | ~1.2 GB | ~830 MB | OTel SDK + middleware ~5-10 MB per service |
| 2 × portal (self-serve + csr) | — | ~270 MB | New v0.4 / v0.5 |
| Postgres (dev config) | ~400 MB | ~400 MB | Unchanged |
| RabbitMQ | ~350 MB | ~350 MB | Unchanged |
| Metabase | ~600 MB | ~600 MB | Unchanged |
| Jaeger (all-in-one image) | — | ~200 MB | New v0.2 |
| **Total (BYOI, services + portals only)** | **~1.5 GB** | **~1.1 GB** | Comfortably under 2 GB |
| **Total (all-in-one, +infra +Jaeger)** | **~2.85 GB** | **~2.65 GB** | Under the 4 GB motto |

BYOI mode fits on a t3.small; all-in-one fits on a t3.medium. The motto-#6 4 GB ceiling holds with headroom.

## Domain boundaries

```
┌─ CRM domain ─────────────────────────────┐
│  Party, Customer, Contact Medium, KYC    │
│  Interaction (audit of touchpoints)      │
│  Case → 1..N Tickets                     │
│  Agent, SLA Policy                       │
│  (hosts Inventory in v0.1)               │
└──────────────────────────────────────────┘

┌─ Inventory domain (inside CRM service) ──┐
│  MSISDN Pool                             │
│  eSIM Profile Pool                       │
└──────────────────────────────────────────┘

┌─ Catalog domain ─────────────────────────┐
│  ProductSpecification                    │
│  ProductOffering (S, M, L)               │
│  ProductOfferingPrice                    │
│  BundleAllowance                         │
│  VAS Offering                            │
│  ServiceSpecification (CFS, RFS)         │
│  ProductToServiceMapping                 │
└──────────────────────────────────────────┘

┌─ Order domain ───────────────────────────┐
│  ProductOrder (COM) ─────decomposes─────┐│
│     │                                    ││
│     └──> ServiceOrder (SOM) ────────────┘│
│              │                            │
│              └──> Service (CFS, RFS)      │
│                      │                    │
│                      └──> ProvisioningTask→ sim
└──────────────────────────────────────────┘

┌─ Subscription domain ────────────────────┐
│  Subscription (FSM)                      │
│  BundleBalance                           │
│  VASPurchase                             │
└──────────────────────────────────────────┘

┌─ Usage → Rating ─────────────────────────┐
│  UsageEvent → RatedDecrement             │
└──────────────────────────────────────────┘

┌─ Audit domain ───────────────────────────┐
│  DomainEvent (outbox + replay substrate) │
└──────────────────────────────────────────┘
```

## Database strategy

### v0.1: single instance, schema-per-domain

```
PostgreSQL 16 (one instance)
├── schema crm
├── schema catalog
├── schema inventory        ← MSISDN + eSIM pools
├── schema payment
├── schema order_mgmt       ← COM
├── schema service_inventory ← SOM output
├── schema provisioning     ← simulator
├── schema subscription
├── schema mediation
├── schema billing
├── schema audit            ← domain event log
└── schema knowledge        ← post-v0.1 (pgvector for runbook RAG)
```

**Services NEVER read each other's schemas directly.** Cross-service queries go through `bss-clients` HTTP. The shared Postgres instance is a deployment convenience, not a coupling — you can verify this by running `grep -r "schema=" services/` and confirming each service only references its own schema.

In BSS-CLI's actual development, the database is an external Postgres on `tech-vm` (reachable via Tailscale). The shared instance also hosts the `campaignos` schema from a separate production workload — Phase 2's migration and `reset-db` target are scoped to only touch the 11 BSS schemas, never `campaignos` or `public`. This is the real test of schema boundary discipline: co-tenanting a dev BSS with a production schema in the same database, without either one touching the other.

### Why one instance for v0.1

- **Simplicity.** One connection pool per service, one backup target, one monitoring target.
- **Transaction guarantees.** The outbox pattern (audit event + domain write in one TX) is trivial.
- **Resource budget.** Motto #6 — one Postgres is ~400 MB, eleven would be ~4.4 GB and blow the budget.
- **MVNO scale reality.** A single well-tuned Postgres handles millions of subscribers. Splitting before measurement is cargo culting.

### The future split path (post-v0.1)

When a single instance becomes the bottleneck, split by schema:

1. Identify the hot schema (likely `subscription` + `mediation` at first)
2. Stand up a new Postgres instance for that schema
3. Update `BSS_DB_URL` env var for the owning service to point to the new instance
4. Migration is a `pg_dump --schema=foo && pg_restore` plus DNS cutover
5. **Zero service code changes** because each service only knows its own `BSS_DB_URL`

This is the test of whether the v0.1 architecture is honest: can you split without rewriting? Yes, because the schema boundaries enforce the isolation in code today.

## AWS deployment path

### Tier 1 — "Ship on AWS today" (~1 day of work)

Target: development, UAT, proof-of-concept for an MVNO stakeholder.

```
┌──────────────────────────────────────────────────┐
│                  AWS Account                      │
│                                                    │
│   Application Load Balancer                       │
│     ├── /catalog/*          → ECS: catalog         │
│     ├── /customer*/*        → ECS: crm             │
│     ├── /payment*/*         → ECS: payment         │
│     ├── /productOrder*/*    → ECS: com             │
│     ├── /serviceOrder*/*    → ECS: som             │
│     ├── /subscription-api/* → ECS: subscription    │
│     ├── /usage*/*           → ECS: mediation       │
│     ├── /rating-api/*       → ECS: rating          │
│     └── /provisioning-api/* → ECS: provisioning-sim│
│                                                    │
│   ECS Fargate cluster — 9 services, 1 task each    │
│                                                    │
│   RDS PostgreSQL (db.t4g.medium)                   │
│   Amazon MQ for RabbitMQ (mq.m5.large)             │
│   ECR for container images                          │
│   CloudWatch Logs (structured JSON)                │
│   Secrets Manager (DB credentials, future auth)    │
│                                                    │
│   Cost estimate: ~$400/month                       │
└──────────────────────────────────────────────────┘
```

**Why this maps cleanly from v0.1:** every service is already a container with the right healthcheck, non-root user, structured logging, and env-driven config. Your Campaign OS ECS Fargate experience transfers directly — it's the same deployment model with different container images.

### Tier 2 — "Small MVNO production" (~1 week on top of v0.1)

Target: launching for a real customer base of 10,000-50,000 subscribers.

Additions on top of Tier 1:
- RDS PostgreSQL **Multi-AZ** for HA
- Amazon MQ **active/standby**
- ECS Fargate **min 2 tasks per service** for rolling deploys and HA
- TLS termination at ALB via ACM certificate
- Route53 for DNS and health checks
- CloudWatch Alarms on key metrics (p99 latency, error rate, queue depth, bundle exhaustion rate)
- Secrets Manager rotation enabled
- WAF basic ruleset on ALB
- **Authentication (Phase 12)** is required before this tier — no TLS-terminated internet exposure without auth

Cost estimate: **~$800-1,200/month** at 10k subscribers.

### Tier 3 — "Scaled MVNO" (post-v0.2, ~1 month of work)

Target: 100k+ subscribers, multi-region, strict SLA.

- **EKS** instead of ECS (better for mixed stateful/stateless workloads at scale)
- **RDS Aurora PostgreSQL** with read replicas, or Aurora per service
- **MSK (Managed Kafka)** replacing RabbitMQ for >20k events/sec
- **ElastiCache Redis** for hot-path caching and rate limiting
- **CloudFront** for eSIM activation asset delivery
- **Shield Advanced**, stricter WAF rules
- **CloudHSM** for real Ki storage (compliance requirement at scale)
- **Multi-region** with cross-region replication for DR

Cost estimate: **~$4,000-8,000/month**.

### Deployability matrix

| Capability | v0.6 status | Notes |
|---|---|---|
| Docker Compose bring-up | ✅ | BYOI is the default shape; all-in-one compose exists for quickstart |
| ECS Fargate | ✅ | Each service is a task definition |
| EKS | ✅ | Same containers, need K8s manifests (not in v0.6) |
| Horizontal scale stateless services | ✅ | Catalog, rating, provisioning-sim scale trivially |
| Horizontal scale stateful services | ⚠️ | Requires consistent-hash routing by customer_id (Phase 13) |
| Multi-AZ database | ✅ | Postgres connection URL is env-driven |
| Zero-downtime deploys | ⚠️ | Needs graceful SIGTERM handler (wired in Phase 3 reference slice) |
| TLS termination | ➖ | Expected at ALB / ingress layer, not per-service |
| Auth between services | ⚠️ | Shared API token (v0.3) via `BSSApiTokenMiddleware` + `TokenAuthProvider`. Per-principal OAuth2 + JWT is Phase 12. `auth_context.py` seam unchanged — Phase 12 fills the principal from JWT claims. |
| Operator-facing portal | ⚠️ | CSR console (v0.5) on port 9002 ships with stub login (NOT real auth). Real OAuth Phase 12. Trusted-network deploy only. |
| Customer-facing portal | ⚠️ | Self-serve signup (v0.4) on port 9001 ships with no inbound auth (it's a public signup surface by design). Network exposure control required. |
| Rate limiting per principal | ❌ | Phase 12 |
| Distributed tracing | ✅ | OpenTelemetry to Jaeger (v0.2). W3C traceparent through HTTP / MQ / SQL. `bss trace` renders ASCII swimlanes. |
| Metrics export | ❌ | Counters/histograms go to structlog only. OTel metrics export decision pending — see ROADMAP.md "Near-term". |
| uv workspace builds in CI | ⚠️ | Per-service Dockerfile with `sed` rewrite workaround (Phase 4 expedient). v0.6 re-evaluated; outcome documented in DECISIONS.md. |
| Schema boundary enforcement | ✅ | Each service only references its own schema; verified by grep. Co-tenant with Campaign OS in dev proves this. |

## Observability (v0.2)

- **OpenTelemetry SDK** in every service via `bss-telemetry`. Auto-instrumentors hook FastAPI (server spans), HTTPX (outbound), AsyncPG (SQL via SQLAlchemy), and aio-pika (MQ publish/consume). W3C `traceparent` propagates through HTTP, MQ messages, and SQL spans automatically.
- **Three manual span sites** add business semantics that auto can't infer: `com.order.complete_to_subscription`, `som.decompose`, `subscription.purchase_vas`. Verified via grep guard.
- **Jaeger all-in-one** as the trace backend. OTLP/HTTP ingress on `:4318`, UI on `:16686`. Memory storage by default; swap to badger for persistence (see `docs/runbooks/jaeger-byoi.md`). Two deploy paths:
  - **Bundled:** `docker-compose.infra.yml` includes the `jaeger` service alongside postgres + rabbitmq + metabase.
  - **BYOI:** install Jaeger once on the same host that already runs Postgres/RabbitMQ (typically tech-vm). Same image, same ports.
- **`bss trace <id>`** queries Jaeger's HTTP API and renders an ASCII swimlane (services as columns, parent-child indented, manual spans starred). Supplements `for-order` / `for-subscription` / `for-ask` resolvers that join through `audit.domain_event.trace_id`.
- **`audit.domain_event.trace_id`** populated on every write by the per-service publishers via `bss_telemetry.current_trace_id()`. Enables post-hoc lookups from a business ID to the full distributed trace.
- **`/health` excluded** from instrumentation (OTel `excluded_urls`). Without this the Jaeger UI is 99% docker-healthcheck noise.
- **structlog** continues to JSON-log; `trace_id` correlation in log lines is present from v0.1 forward-compat work.
- **Metabase** reads from `audit.domain_event` for business dashboards (separate from OTel — different consumer of the same audit substrate).

## What's NOT in the architecture

- **No API gateway.** CLI talks directly to services. Simpler, lower latency, easier to debug. ALB is the gateway in AWS deployments.
- **No service mesh.** Docker network / VPC routing is sufficient below 100k RPS.
- **No Kafka.** RabbitMQ is lighter, simpler, and topic exchanges cover v0.1 needs. Migration path to MSK is documented for Tier 3.
- **No Redis.** Postgres is fast enough for v0.1 workload.
- **No authentication.** Phase 12. The architecture is shaped for clean addition via `auth_context.py` per service.
- **No multi-tenancy at runtime.** `tenant_id` columns exist but default to `'DEFAULT'`. Activating true tenancy is a v0.3 concern.
- **No eKYC implementation.** Channel-layer concern. BSS-CLI receives signed attestations via `customer.attest_kyc` and enforces policies.
- **No physical SIM logistics.** eSIM-only in v0.1.
- **No strict event ordering.** Consumers must handle concurrent events causally via policy checks, not assume arrival order. See "Event ordering guarantees" section above.
- **No Online Charging System (OCS).** BSS-CLI does not implement Diameter Gy/Ro, PCEF quota grants, quota reservation, or `Final-Unit-Indication` signalling to the packet core. OCS is abstracted outside the solution — a real deployment would have an external OCS on the network side making live authorize/deny decisions against the PCEF/GGSN. Our Mediation service is **TMF635 online mediation**: single-event ingest with synchronous block-at-edge policy, driving balance decrement via events. It collapses the customer-facing accounting surface of an OCS (quota depletion → block) into a TMF-shaped REST API, but it does not sit on the data plane.
- **No batch mediation.** No CDR file ingest, no hourly/daily aggregation jobs, no rerating windows, no deduplication/correlation pipelines. Motto #1 (bundled-prepaid only) removes the reason batch mediation exists — there are no per-unit charges to roll up into an invoice. If post-paid is ever introduced (v0.3+), a batch-rating plane would need to be added alongside the current online path; it is not a modification of it.
