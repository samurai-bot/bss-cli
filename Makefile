.PHONY: help up up-all up-minimal up-core down build test fmt lint

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
	uv run pytest

fmt:
	uv run ruff format .

lint:
	uv run ruff check . && uv run mypy .
