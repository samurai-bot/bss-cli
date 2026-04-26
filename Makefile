.PHONY: help up up-all up-minimal up-core down build test fmt lint migrate seed reset-db check-clock doctrine-check python-check scenarios scenarios-hero

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
	@echo "  doctrine-check   — run all v0.6+ grep guards (clock, channel, portals, no-bypass)"
	@echo "  python-check     — warn if active Python is outside the supported 3.12 range"

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

python-check:
	@# Project targets Python 3.12 (CLAUDE.md "Tech stack"). Newer minors
	@# (e.g. 3.14) work mostly but have surfaced regressions:
	@# `asyncio.get_event_loop()` removed in 3.14, Pydantic V1 deprecation
	@# warnings under LangChain. Earlier minors (<3.12) lack syntax we use.
	@# This is a warn-only check — never fails the build, just flags drift.
	@v=$$(uv run python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'); \
	case "$$v" in \
		3.12) echo "✓ python $$v (supported)" ;; \
		3.13) echo "⚠ python $$v — newer than 3.12 target; should work but untested. See CLAUDE.md tech-stack." ;; \
		*)   echo "⚠ python $$v — outside supported 3.12 range. Recreate venv: uv python install 3.12.13 && uv venv --python 3.12.13" ;; \
	esac

test:
	@failed=0; \
	for dir in packages/bss-clients packages/bss-admin packages/bss-clock packages/bss-events packages/bss-telemetry packages/bss-middleware packages/bss-portal-ui services/catalog services/crm services/payment services/subscription services/com services/som services/provisioning-sim services/mediation services/rating orchestrator cli portals/self-serve portals/csr; do \
		printf "\n══ $$dir ══\n"; \
		PYTHONPATH=$$dir/tests:$$dir:$$PYTHONPATH uv run pytest $$dir/tests/ -v -m "not integration" || failed=1; \
	done; \
	if [ $$failed -eq 1 ]; then printf "\n✗ Some suites failed\n"; exit 1; \
	else printf "\n✓ All suites passed\n"; fi

check-clock:
	@# Every business-logic site must route through bss_clock.now().
	@# bss-clock impl, the `bss clock` cmd surface, the renderer wall-clock fallback,
	@# tests, and any line carrying `# noqa: bss-clock` are exempt.
	@hits=$$(grep -rnE "datetime\.(utcnow|now)" --include="*.py" \
		services/ packages/ orchestrator/ cli/bss_cli/ portals/ 2>/dev/null \
		| grep -v "packages/bss-clock/" \
		| grep -v "cli/bss_cli/commands/clock.py" \
		| grep -v "/tests/" \
		| grep -v "# noqa: bss-clock" \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ business logic must import clock_now from bss_clock:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ all datetime.now sites route through bss_clock"

doctrine-check: check-clock
	@# v0.6 wrapper around all grep-guard doctrine checks.
	@# Adds: portal-handlers don't write via bss-clients (v0.4+),
	@# and OTel imports stay out of business-logic services/policies (v0.2).
	@hits=$$(grep -rnE '\.(create|charge|purchase_vas|terminate|add_card|remove_method|cancel)\(' \
		--include='*.py' portals/*/bss_*/routes/ 2>/dev/null \
		| grep -v 'session_store.create\|store.create\|ask_about_customer' \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ portal route handlers must not call mutating bss-clients:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ portal handlers route writes through agent_bridge"
	@hits=$$(grep -rn 'from opentelemetry' --include='*.py' \
		services/*/app/services/ services/*/app/policies/ 2>/dev/null \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ OTel imports leaked into service/policy layer:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ OTel surfaces stay out of services/ and policies/"
	@hits=$$(grep -rn 'campaignos' services/ cli/ orchestrator/ portals/ packages/ scenarios/ 2>/dev/null \
		| grep -v '/alembic/versions/' \
		| grep -v '# noqa: campaignos' \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ campaign OS reference leaked:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ campaign OS untouched"
	@# v0.7+ — renewal must read the price snapshot, never query the active catalog.
	@# `get_active_price` is the active-aware lookup forbidden in the renewal stack.
	@# `get_offering_price` (no `_active_`) is the snapshot resolve and is allowed —
	@# it fetches a price row by id without any time filter.
	@hits=$$(awk '/async def renew\b/,/^    async def [a-z]/' \
		services/subscription/app/services/subscription_service.py 2>/dev/null \
		| grep -nE 'get_active_price' \
		|| true); \
	if [ -n "$$hits" ]; then \
		echo "✗ subscription.renew() must not query catalog active-price APIs:"; \
		echo "$$hits"; \
		exit 1; \
	fi; \
	echo "✓ renewal reads snapshot, not catalog"

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
