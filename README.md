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
docker compose up -d          # brings up 9 BSS services only
make migrate
make seed
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

## Quick start (all-in-one)

Brings up the 9 services plus PostgreSQL, RabbitMQ, and Metabase.

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

Scenarios in `scenarios/*.yaml` are the living regression suite. Three
are tagged `hero` and gate v0.1 — two are fully deterministic (signup
→ exhaustion, fault-injected provisioning with retry), the third hands
a blocked subscription to the LLM supervisor in plain English and
asserts the model diagnoses, tops up, and logs the interaction without
touching destructive tools.

## License

Apache-2.0
