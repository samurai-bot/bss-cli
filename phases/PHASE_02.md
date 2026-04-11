# Phase 2 — Data Model + Seed Data (v2)

## Goal

All 38 tables exist via a single clean Alembic migration. Seed reference data loads via `make seed`. Every later phase assumes the schema and seed are in place.

**Single PostgreSQL 16 instance, schema-per-domain.** Each service has its own `BSS_DB_URL` pointing at the shared instance and only touches its own schema. The boundary is enforced socially in v0.1, mechanically in any later split.

## Deliverables

### 1. Shared models package

```
packages/bss-models/
├── bss_models/
│   ├── __init__.py
│   ├── base.py              # SQLAlchemy 2.0 DeclarativeBase, naming conventions
│   ├── types.py             # custom column types
│   ├── crm.py               # 10 tables (incl. customer_identity for KYC)
│   ├── catalog.py           # 7 tables
│   ├── inventory.py         # 2 tables (msisdn_pool + esim_profile)
│   ├── payment.py           # 2 tables
│   ├── order_mgmt.py        # 3 tables
│   ├── service_inventory.py # 4 tables
│   ├── provisioning.py      # 2 tables
│   ├── subscription.py      # 4 tables
│   ├── mediation.py         # 1 table
│   ├── billing.py           # 2 tables
│   └── audit.py             # 1 table
├── alembic/
│   └── versions/
│       └── 0001_initial.py  # ALL 36 tables in ONE migration
├── alembic.ini
└── pyproject.toml
```

**Rule:** ship with a single initial migration. Don't fragment before v0.2.

### 2. Shared seed package (reference data only)

```
packages/bss-seed/
├── bss_seed/
│   ├── main.py
│   ├── catalog.py      # plans, VAS, service specs, mappings
│   ├── inventory.py    # 1000 MSISDNs
│   ├── crm.py          # 5 agents, 12 SLA policies
│   └── provisioning.py # 5 fault rules (disabled)
└── pyproject.toml
```

Seed customers with COF are created in Phase 10 via a scenario, not here. The seed package is reference-data-only so it has no dependency on any service.

### 3. Makefile additions

```makefile
migrate:
	uv run --package bss-models alembic upgrade head

seed:
	uv run --package bss-seed python -m bss_seed.main

reset-db:
	docker compose exec postgres psql -U bss -d bss -c "DROP SCHEMA IF EXISTS crm, catalog, inventory, payment, order_mgmt, service_inventory, provisioning, subscription, mediation, billing, audit CASCADE;"
	$(MAKE) migrate && $(MAKE) seed
```

## Seed data

### Plans
- `PLAN_S` Lite — SGD 10/mo — data 5GB, voice 100min, SMS 100
- `PLAN_M` Standard — SGD 25/mo — data 30GB, voice unlimited, SMS unlimited
- `PLAN_L` Max — SGD 45/mo — data 150GB, voice unlimited, SMS unlimited

Unlimited is encoded as `quantity = -1`.

### VAS
- `VAS_DATA_1GB` — SGD 3 — +1GB data, no expiry
- `VAS_DATA_5GB` — SGD 12 — +5GB data, no expiry
- `VAS_UNLIMITED_DAY` — SGD 5 — ~unlimited data, 24h expiry

### Service specs & mappings
- `SSPEC_CFS_MOBILE_BROADBAND` (CFS)
- `SSPEC_RFS_DATA_BEARER` (RFS)
- `SSPEC_RFS_VOICE_BEARER` (RFS)
- All three plans map to this CFS + both RFS (v0.1 simplification)

### Agents
- AGT-001 Alice Tan (csr)
- AGT-002 Bob Lim (csr)
- AGT-003 Carol Ng (supervisor)
- AGT-004 Dave Koh (engineer)
- AGT-SYS System (system)

### SLA policies (12 total)
4 priorities × 3 ticket types (billing_dispute, service_outage, configuration). Example targets (minutes):
- billing_dispute: low 2880, normal 1440, high 480, urgent 120
- service_outage: low 480, normal 240, high 60, urgent 30
- configuration: low 2880, normal 1440, high 720, urgent 240

### MSISDN pool
1000 numbers, `90000000`–`90000999`, all `available`.

### eSIM profile pool
1000 profiles, all `available`. Each profile seeded with:
- `iccid` = `"8910101" + str(i).zfill(12)` where i = 0..999
- `imsi` = `"525010000" + str(i).zfill(6)` (Singapore-ish MCC/MNC format for realism)
- `ki_ref` = `f"hsm://ref/{uuid4()}"` — STRING REFERENCE, never a real Ki
- `smdp_server` = `"smdp.bss-cli.local"`
- `matching_id` = 16-char random
- `activation_code` = `f"LPA:1${{smdp_server}}${{matching_id}}"`

Loud comment in seed script: `# NEVER store actual Ki values. ki_ref is a reference to a hypothetical HSM slot. Real Ki storage is HSM territory and explicitly out of scope for BSS-CLI.`

### Fault injection rules (all disabled)
Seeded so scenarios can enable them by ID without having to create them:
- HLR_PROVISION / fail_first_attempt / p=0.30
- HLR_PROVISION / stuck / p=0.05
- PCRF_POLICY_PUSH / slow / p=0.20
- OCS_BALANCE_INIT / fail_first_attempt / p=0.10
- ESIM_PROFILE_PREPARE / fail_first_attempt / p=0.15
- HLR_DEPROVISION / stuck / p=0.05

## Verification checklist

- [ ] `make migrate` runs clean from empty DB
- [ ] `make seed` populates reference data, idempotent on re-run
- [ ] `make reset-db` works end-to-end
- [ ] `\dt *.*` in psql shows all 38 tables across 11 schemas
- [ ] `SELECT COUNT(*) FROM inventory.msisdn_pool` = 1000
- [ ] `SELECT COUNT(*) FROM inventory.esim_profile` = 1000
- [ ] `SELECT COUNT(*) FROM crm.agent` = 5
- [ ] `SELECT COUNT(*) FROM crm.sla_policy` = 12
- [ ] `SELECT COUNT(*) FROM catalog.product_offering` = 3
- [ ] `SELECT COUNT(*) FROM catalog.vas_offering` = 3
- [ ] `SELECT COUNT(*) FROM catalog.service_specification` = 3
- [ ] `SELECT COUNT(*) FROM provisioning.fault_injection WHERE enabled=false` = 6
- [ ] **No ki_ref contains anything resembling a real hex key** — all are `hsm://ref/<uuid>` format
- [ ] Alembic downgrade-to-base-then-upgrade works
- [ ] SQLAlchemy naming conventions applied

## Out of scope

- Multiple migrations (single `0001_initial.py`)
- Seed customers with COF (Phase 10 scenario)
- Data factories / fixtures (per-service in later phases)
- Performance tuning

## Session prompt

> Read `CLAUDE.md`, `DATA_MODEL.md`, `phases/PHASE_02.md`.
>
> Before coding, enumerate every table you will create and confirm it matches `DATA_MODEL.md` exactly. Flag ambiguities. Wait for approval, then implement models → migration → seed package in that order.
>
> After implementation, run the verification checklist and paste results. Do not commit.

## The discipline

If model code and `DATA_MODEL.md` disagree, the doc wins. Fix the doc first in a separate small commit, then fix the code. Never let them drift silently.
