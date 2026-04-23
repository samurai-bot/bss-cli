# BSS-CLI

> The entire BSS, in a terminal. SID-aligned. TMF-compliant. LLM-native. eSIM-first.

BSS-CLI is a lightweight, reference-implementation Business Support System for a mobile prepaid MVNO. It covers CRM (with case/ticket management), Product Catalog, Commercial Order Management, Service Order Management with a provisioning simulator, eSIM profile management, Subscription, Bundle Balance, Mediation, Rating, and Payment — all running in under 4GB RAM, all driven from a single `bss` command.

Every operation is a tool the LLM can call. The UI is the terminal plus ASCII visualizations. Metabase is the only graphical surface, reserved for analytics.

## Motto principles

1. Bundled-prepaid only. No dunning, no proration, no credit risk.
2. Card-on-file is mandatory.
3. Block-on-exhaust. VAS top-up is the only unblock path.
4. CLI-first, LLM-native.
5. TMF-compliant where it counts.
6. Lightweight is measurable (<4GB RAM, <30s cold start, <50ms p99 API).
7. Writes go through a policy layer. No raw CRUD.

## Quick start (bring your own infra)

Assumes you already have PostgreSQL 16 and RabbitMQ 3.13 running.

```bash
git clone <repo>
cd bss-cli
cp .env.example .env          # edit DB/MQ connection strings
# v0.3+ requires an API token — generate one and replace 'changeme':
sed -i "s/^BSS_API_TOKEN=changeme$/BSS_API_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d          # brings up 9 BSS services only
make migrate
make seed
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

## Quick start (all-in-one)

Brings up the 9 services plus PostgreSQL, RabbitMQ, Metabase, **and Jaeger**.

```bash
docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d
make migrate
make seed
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

## Authentication (v0.3)

Every BSS service requires `X-BSS-API-Token: <BSS_API_TOKEN>` on every request. The CLI, orchestrator, and scenario runner all read `BSS_API_TOKEN` from `.env` and inject the header automatically — no per-call wiring.

```bash
# Generate a token (≥32 chars; the .env.example sentinel "changeme" is rejected at startup)
openssl rand -hex 32

# Edit .env and replace BSS_API_TOKEN=changeme with the value above.
# Services fail to start until you do this.
```

The exemption allowlist for unauthenticated requests is exactly `/health`, `/health/ready`, `/health/live` — nothing else (not `/docs`, not `/openapi.json`). For the rotation procedure see [`docs/runbooks/api-token-rotation.md`](docs/runbooks/api-token-rotation.md).

This is intentionally the smallest possible auth story (one shared admin token; no roles, no per-principal claims). OAuth2 with real RBAC is Phase 12 — see `CLAUDE.md`.

## Tracing (v0.2)

Every service exports OpenTelemetry traces to Jaeger. After a scenario run, see the full distributed trace in three ways:

```bash
# ASCII swimlane in the terminal
bss trace for-order ORD-014

# By trace ID directly
bss trace get 4a8f9e2c0123456789abcdef01234567

# Open Jaeger UI
open http://localhost:16686/         # all-in-one
open http://tech-vm:16686/           # BYOI
```

For BYOI installs (Jaeger on a separate host like `tech-vm`), see [`docs/runbooks/jaeger-byoi.md`](docs/runbooks/jaeger-byoi.md). Set `BSS_OTEL_EXPORTER_OTLP_ENDPOINT` in `.env` to point services at the right Jaeger.

## Documentation

- `CLAUDE.md` — Project doctrine (read this first)
- `ARCHITECTURE.md` — Services, topology, call patterns, AWS deployment
- `DATA_MODEL.md` — ~38 tables across 11 schemas in one Postgres instance
- `TOOL_SURFACE.md` — The ~65 LLM tools
- `phases/` — Phase-by-phase build plan
- `DECISIONS.md` — Architecture decision log
- `SHIP_CRITERIA.md` — v0.1 ship-gate checklist (run before cutting the tag)
- `docs/runbooks/` — Procedural knowledge (seed content in v0.1, RAG-indexed in v0.2)

## Scenario harness

```bash
bss scenario list scenarios                   # inventory
bss scenario validate scenarios/*.yaml        # parse-check
bss scenario run scenarios/<name>.yaml        # single run
bss scenario run-all scenarios --tag hero     # filter by tag
make scenarios                                # every scenario in ./scenarios
make scenarios-hero                           # just the three ship-gate scenarios
```

Scenarios in `scenarios/*.yaml` are the living regression suite. Four
are tagged `hero`. Three gate v0.1 — two are fully deterministic (signup
→ exhaustion, fault-injected provisioning with retry), the third hands
a blocked subscription to the LLM supervisor in plain English and
asserts the model diagnoses, tops up, and logs the interaction without
touching destructive tools. The fourth (`trace_customer_signup_swimlane`)
gates v0.2 — drives a signup, then asserts the resulting OTel trace
has the expected span fan-out and zero errors.

## License

Apache-2.0
