# BSS-CLI

> The entire BSS, in a terminal. SID-aligned. TMF-compliant. LLM-native. eSIM-first.

BSS-CLI is a lightweight, reference-implementation Business Support System for a mobile prepaid MVNO. It covers CRM (with case/ticket management), Product Catalog, Commercial Order Management, Service Order Management with a provisioning simulator, eSIM profile management, Subscription, Bundle Balance, Mediation, Rating, Billing, and Payment — all running in under 4GB RAM, all driven from a single `bss` command.

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
docker compose up -d          # brings up 10 BSS services only
make migrate
make seed
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

## Quick start (all-in-one)

Brings up the 10 services plus PostgreSQL, RabbitMQ, and Metabase.

```bash
docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d
make migrate
make seed
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

## Documentation

- `CLAUDE.md` — Project doctrine (read this first)
- `ARCHITECTURE.md` — Services, topology, call patterns, AWS deployment
- `DATA_MODEL.md` — ~38 tables across 11 schemas in one Postgres instance
- `TOOL_SURFACE.md` — The ~65 LLM tools
- `phases/` — Phase-by-phase build plan
- `DECISIONS.md` — Architecture decision log
- `docs/runbooks/` — Procedural knowledge (seed content in v0.1, RAG-indexed in v0.2)

## License

Apache-2.0
