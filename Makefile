.PHONY: help up up-all up-minimal up-core down build test fmt lint migrate seed reset-db

help:
	@echo "  up          — 10 BSS services (BYOI Postgres/RabbitMQ)"
	@echo "  up-all      — services + Postgres + RabbitMQ + Metabase"
	@echo "  up-minimal  — catalog + crm + payment only"
	@echo "  up-core     — minimal + com + som + subscription + provisioning-sim"
	@echo "  down        — stop everything"
	@echo "  build       — build all service images"
	@echo "  test        — run pytest"
	@echo "  fmt         — format with ruff"
	@echo "  lint        — lint with ruff + mypy"

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
	uv run pytest || test $$? -eq 5

fmt:
	uv run ruff format .

lint:
	uv run ruff check . && uv run mypy .

# --- Data Model ---

# Derive psql-compatible URL by stripping +asyncpg driver suffix
BSS_PSQL_URL := $(subst +asyncpg,,$(BSS_DB_URL))

migrate:
	cd packages/bss-models && uv run --package bss-models alembic upgrade head

seed:
	uv run --package bss-seed python -m bss_seed.main

reset-db:
	psql "$(BSS_PSQL_URL)" -c "DROP SCHEMA IF EXISTS crm, catalog, inventory, payment, order_mgmt, service_inventory, provisioning, subscription, mediation, billing, audit CASCADE;"
	psql "$(BSS_PSQL_URL)" -c "DELETE FROM public.alembic_version;" 2>/dev/null || true
	$(MAKE) migrate
	$(MAKE) seed
