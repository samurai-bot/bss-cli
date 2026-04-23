.PHONY: help up up-all up-minimal up-core down build test fmt lint migrate seed reset-db check-clock scenarios scenarios-hero

help:
	@echo "  up               — 10 BSS services (BYOI Postgres/RabbitMQ)"
	@echo "  up-all           — services + Postgres + RabbitMQ + Metabase"
	@echo "  up-minimal       — catalog + crm + payment only"
	@echo "  up-core          — minimal + com + som + subscription + provisioning-sim"
	@echo "  down             — stop everything"
	@echo "  build            — build all service images"
	@echo "  test             — run pytest"
	@echo "  fmt              — format with ruff"
	@echo "  lint             — lint with ruff + mypy"
	@echo "  scenarios        — run every scenario in ./scenarios (including LLM ask: steps)"
	@echo "  scenarios-hero   — run only the three hero ship-gate scenarios"
	@echo "  check-clock      — grep guard: all datetime.now sites route through bss-clock"

up:
	docker compose up -d

up-all:
	docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d

up-minimal:
	docker compose up -d catalog crm payment

up-core:
	docker compose up -d catalog crm payment com som subscription provisioning-sim

down:
	docker compose -f docker-compose.yml -f docker-compose.infra.yml down

build:
	docker compose build

test:
	@failed=0; \
	for dir in packages/bss-clients packages/bss-admin packages/bss-clock packages/bss-events packages/bss-telemetry packages/bss-middleware packages/bss-portal-ui services/catalog services/crm services/payment services/subscription services/com services/som services/provisioning-sim services/mediation services/rating orchestrator cli portals/self-serve portals/csr; do \
		printf "\n══ $$dir ══\n"; \
		PYTHONPATH=$$dir:$$PYTHONPATH uv run pytest $$dir/tests/ -v -m "not integration" || failed=1; \
	done; \
	if [ $$failed -eq 1 ]; then printf "\n✗ Some suites failed\n"; exit 1; \
	else printf "\n✓ All suites passed\n"; fi

check-clock:
	@# Every business-logic site must route through bss_clock.now().
	@# Tests, CLI, and the bss-clock package itself are allowed to call datetime.now directly.
	@hits=$$(grep -rnE "datetime\.(utcnow|now)" --include="*.py" services/ packages/ orchestrator/ 2>/dev/null \
		| grep -v "packages/bss-clock/" \
		| grep -v "/tests/" \
		| grep -v "# noqa: bss-clock" \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ business logic must import clock_now from bss_clock:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ all datetime.now sites route through bss_clock"

fmt:
	uv run ruff format .

lint:
	uv run ruff check . && uv run mypy .

# --- Data Model ---

# Source .env (if present) inside every recipe that needs DB/MQ creds. `set -a`
# exports every var until `set +a`, so children (alembic, psql, bss-seed) inherit them.
ENV_SOURCE := if [ -f .env ]; then set -a; . ./.env; set +a; fi

migrate:
	@$(ENV_SOURCE); cd packages/bss-models && uv run --package bss-models alembic upgrade head

seed:
	@$(ENV_SOURCE); uv run --package bss-seed python -m bss_seed.main

scenarios:
	@uv run bss scenario run-all scenarios

scenarios-hero:
	@uv run bss scenario run-all scenarios --tag hero

reset-db:
	@$(ENV_SOURCE); \
	PSQL_URL=$$(echo "$$BSS_DB_URL" | sed 's|+asyncpg||'); \
	psql "$$PSQL_URL" -c "DROP SCHEMA IF EXISTS crm, catalog, inventory, payment, order_mgmt, service_inventory, provisioning, subscription, mediation, billing, audit CASCADE;"; \
	psql "$$PSQL_URL" -c "DELETE FROM public.alembic_version;" 2>/dev/null || true; \
	$(MAKE) migrate; \
	$(MAKE) seed
