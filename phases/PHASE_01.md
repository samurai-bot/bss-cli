# Phase 1 — Monorepo Skeleton + Infrastructure (v3)

## Goal

Clean `uv` workspace, empty service directories, split docker-compose setup (BSS services default + optional infra), Makefile, env template. `docker compose up -d` boots 10 empty Python containers that pass healthchecks. No business logic.

## Repo layout

```
bss-cli/
├── README.md, LICENSE, CLAUDE.md, ARCHITECTURE.md,
├── DATA_MODEL.md, TOOL_SURFACE.md, DECISIONS.md
├── docker-compose.yml               # 10 BSS services ONLY (default)
├── docker-compose.infra.yml         # Postgres + RabbitMQ + Metabase (optional)
├── .env.example
├── Makefile
├── pyproject.toml                   # uv workspace root
├── packages/
│   ├── bss-models/                  # Phase 2
│   ├── bss-events/                  # Phase 3
│   ├── bss-clients/                 # Phase 5
│   └── bss-seed/                    # Phase 2
├── services/
│   ├── _template/                   # Dockerfile + app skeleton
│   ├── catalog/ crm/ payment/ com/ som/
│   ├── subscription/ mediation/ rating/
│   ├── billing/ provisioning-sim/
├── cli/                             # Phase 9
├── orchestrator/                    # Phase 9
├── docs/runbooks/                   # Phase 11 (seed dir in v0.1)
└── scenarios/                       # Phase 10
```

## docker-compose.yml (services only — default shape)

10 BSS services. Each reads `BSS_DB_URL` and `BSS_MQ_URL` from `.env`. Assumes Postgres + RabbitMQ reachable via those URLs (whether from the optional infra compose or external managed services).

```yaml
x-bss-service: &bss-service
  env_file: .env
  restart: unless-stopped
  networks: [bss]

services:
  catalog:          { <<: *bss-service, build: { context: ., dockerfile: services/catalog/Dockerfile },         ports: ["8001:8000"] }
  crm:              { <<: *bss-service, build: { context: ., dockerfile: services/crm/Dockerfile },             ports: ["8002:8000"] }
  payment:          { <<: *bss-service, build: { context: ., dockerfile: services/payment/Dockerfile },         ports: ["8003:8000"] }
  com:              { <<: *bss-service, build: { context: ., dockerfile: services/com/Dockerfile },             ports: ["8004:8000"] }
  som:              { <<: *bss-service, build: { context: ., dockerfile: services/som/Dockerfile },             ports: ["8005:8000"] }
  subscription:     { <<: *bss-service, build: { context: ., dockerfile: services/subscription/Dockerfile },    ports: ["8006:8000"] }
  mediation:        { <<: *bss-service, build: { context: ., dockerfile: services/mediation/Dockerfile },       ports: ["8007:8000"] }
  rating:           { <<: *bss-service, build: { context: ., dockerfile: services/rating/Dockerfile },          ports: ["8008:8000"] }
  billing:          { <<: *bss-service, build: { context: ., dockerfile: services/billing/Dockerfile },         ports: ["8009:8000"] }
  provisioning-sim: { <<: *bss-service, build: { context: ., dockerfile: services/provisioning-sim/Dockerfile }, ports: ["8010:8000"] }

networks:
  bss: { driver: bridge }
```

Profiles: `minimal` (catalog, crm, payment), `core` (+com, som, subscription, provisioning-sim), `full` (all 10). Default = all 10.

## docker-compose.infra.yml (optional)

Separate file. Brought up with `-f docker-compose.yml -f docker-compose.infra.yml`.

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: bss, POSTGRES_PASSWORD: bss, POSTGRES_DB: bss }
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck: { test: ["CMD", "pg_isready", "-U", "bss"], interval: 10s, retries: 5 }
    networks: [bss]
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports: ["5672:5672", "15672:15672"]
    volumes: [rabbitmq_data:/var/lib/rabbitmq]
    healthcheck: { test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"], interval: 10s, retries: 5 }
    networks: [bss]
  metabase:
    image: metabase/metabase:latest
    ports: ["3000:3000"]
    environment:
      MB_DB_TYPE: postgres
      MB_DB_DBNAME: bss
      MB_DB_PORT: 5432
      MB_DB_USER: bss
      MB_DB_PASS: bss
      MB_DB_HOST: postgres
    depends_on: [postgres]
    networks: [bss]

volumes: { postgres_data: {}, rabbitmq_data: {} }
networks: { bss: { external: false } }
```

## .env.example

```bash
# Shared connection strings
BSS_DB_URL=postgresql+asyncpg://bss:bss@postgres:5432/bss
BSS_MQ_URL=amqp://guest:guest@rabbitmq:5672/
BSS_ENV=development
BSS_LOG_LEVEL=INFO
BSS_TENANT_DEFAULT=DEFAULT

# KYC enforcement (Phase 4+)
BSS_REQUIRE_KYC=false

# Clock (Phase 2+)
BSS_CLOCK_MODE=system

# LLM (Phase 9)
BSS_LLM_BASE_URL=http://litellm:4000
BSS_LLM_MODEL=mimo-v2-flash
BSS_LLM_API_KEY=sk-local-dev

# Feature flags
BSS_ENABLE_TEST_ENDPOINTS=false
BSS_ALLOW_DESTRUCTIVE=false
```

For all-in-one: use compose service names (`postgres`, `rabbitmq`) in URLs. For BYOI: edit `.env` with managed service endpoints.

## Service template essentials

**`services/_template/app/main.py`:**
```python
from fastapi import FastAPI
from app.config import settings
from app.logging import configure_logging
from app.lifespan import lifespan

configure_logging(settings.log_level)
app = FastAPI(title=settings.service_name, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.service_name}

@app.get("/ready")
async def ready():
    return {"status": "ready", "service": settings.service_name}
```

**`app/lifespan.py`** — graceful SIGTERM (handles rolling deploys):
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service.starting")
    # Phase 2+: DB engine, Phase 3+: MQ connection
    yield
    log.info("service.stopping")
    # Phase 2+: close DB, Phase 3+: drain consumers
```

**`app/auth_context.py`** — Phase 12-ready abstraction:
```python
from dataclasses import dataclass, field
from contextvars import ContextVar

@dataclass
class AuthContext:
    actor: str = "system"
    tenant: str = "DEFAULT"
    roles: list[str] = field(default_factory=lambda: ["admin"])
    permissions: list[str] = field(default_factory=lambda: ["*"])
    channel: str = "system"

_current: ContextVar[AuthContext] = ContextVar("auth_context", default=AuthContext())

def current() -> AuthContext:
    return _current.get()

def set_for_request(actor: str, tenant: str, channel: str) -> None:
    _current.set(AuthContext(actor=actor, tenant=tenant, channel=channel))

def has_permission(permission: str) -> bool:
    ctx = current()
    return "*" in ctx.permissions or permission in ctx.permissions
```

All policies and routers read from `auth_context.current()`. Phase 12 replaces only this module + middleware.

**Dockerfile template** (copied per service with `SERVICE` substitution):
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
ARG SERVICE
COPY packages/ packages/
COPY services/${SERVICE}/ service/
RUN uv sync --package ${SERVICE}

FROM python:3.12-slim AS runtime
RUN useradd -m -u 1000 bss && apt-get update && \
    apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
ARG SERVICE
COPY --from=builder --chown=bss:bss /build /app
WORKDIR /app/service
USER bss
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Makefile

```makefile
.PHONY: help up up-all down build test fmt lint

help:
	@echo "  up       — 10 BSS services (BYOI Postgres/RabbitMQ)"
	@echo "  up-all   — services + Postgres + RabbitMQ + Metabase"
	@echo "  down     — stop everything"

up:
	docker compose up -d

up-all:
	docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d

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
```

## Verification checklist

- [ ] `uv sync` succeeds from repo root
- [ ] `docker compose build` builds all 10 service images
- [ ] `make up-all` brings up 13 containers (10 services + postgres + rabbitmq + metabase)
- [ ] All 10 services return 200 on `/health` and `/ready`
- [ ] `docker stats` total < 3 GB for all-in-one
- [ ] `docker stats` services-only < 2 GB
- [ ] structlog JSON output visible in `docker compose logs`
- [ ] No hardcoded URLs/ports outside config.py (grep to verify)
- [ ] `auth_context.py` present and importable in every service
- [ ] `make down` stops cleanly, no ERROR logs on shutdown
- [ ] BYOI path verified: stop infra compose, point `.env` at a different Postgres, services still come up

## Out of scope

- SQL models (Phase 2)
- Business logic (Phase 3+)
- API endpoints beyond health/ready
- CI setup (post-v0.1)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `phases/PHASE_01.md`.
>
> Before coding:
> 1. Confirm the repo layout matches what's specified
> 2. List every file you will create (should be ~40 files)
> 3. Confirm the split compose approach: default = services only, infra = optional add-on
>
> Wait for approval. Then scaffold: workspace root → service template → 10 service clones → compose files → Makefile → env template.
>
> Verification: `make up-all` → all 13 containers healthy. Then `docker compose down` + edit `.env` to point at a different Postgres → `make up` → verify BYOI path works. Do not commit.

## The discipline

**Containers stay empty.** This phase is boring infrastructure. If Claude Code starts adding business logic, stop it.

**The service template is the contract.** All 10 services start identical. Any divergence during scaffolding = fix the template and re-sync.

**The split compose is the point.** Do not merge the two files "for convenience". The BYOI path is the default deployment story, not an afterthought.
