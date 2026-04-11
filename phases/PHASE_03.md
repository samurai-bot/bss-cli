# PHASE 03 — First vertical slice: Catalog service

## Goal

Build the **reference pattern** for all subsequent services. After this phase, every other service is a clone of the structure established here. Pick `catalog` because it is read-mostly, has no state machine, and exercises every architectural decision (TMF compliance, async SQLAlchemy, repository pattern, structured logging, testing).

> **This is the most important phase of the entire project.** Spend extra effort. Get the pattern right. The next 4 phases will replicate it.

## In scope

- `services/catalog/` FastAPI application
- TMF620 Product Catalog Management v4 read endpoints:
  - `GET /tmf-api/productCatalogManagement/v4/productOffering`
  - `GET /tmf-api/productCatalogManagement/v4/productOffering/{id}`
  - `GET /tmf-api/productCatalogManagement/v4/productSpecification`
  - `GET /tmf-api/productCatalogManagement/v4/productSpecification/{id}`
  - Plus a non-TMF custom endpoint for VAS: `GET /vas/offering`, `GET /vas/offering/{id}` (no TMF API for VAS)
- TMF620-compliant Pydantic response schemas (use exact field names from the spec: `lifecycleStatus`, `productOfferingPrice`, etc.)
- Repository pattern: `bss_catalog/repository.py` wraps SQLAlchemy queries; FastAPI dependencies inject sessions and repos
- App factory: `bss_catalog/app.py` exposes `create_app()`; main entry in `bss_catalog/__main__.py` runs `uvicorn`
- Configuration via `pydantic-settings`, env-driven, no hardcoded values
- Structured logging via `structlog`, JSON output, includes request ID
- Request ID middleware: generates UUID, propagates via `X-Request-ID` header, attaches to log context
- Health endpoint: `GET /health` returns `{ "status": "ok", "service": "catalog", "version": "0.1.0" }`
- Readiness endpoint: `GET /ready` checks DB connectivity
- OpenAPI docs at `/docs` (FastAPI default)
- Dockerfile (multi-stage, slim, non-root user)
- Add `catalog` to `docker-compose.yml`
- Tests:
  - `tests/test_catalog_api.py` — pytest-asyncio + httpx ASGI client, hits all endpoints, asserts TMF schema shape
  - `tests/test_catalog_repository.py` — repository unit tests against testcontainers postgres
  - `conftest.py` shared fixtures for async DB session, app factory, seeded test data

## Architectural decisions to lock in (these become the pattern)

1. **Service layout:**
   ```
   services/catalog/
   ├── pyproject.toml
   ├── Dockerfile
   ├── bss_catalog/
   │   ├── __init__.py
   │   ├── __main__.py
   │   ├── app.py              ← create_app() factory
   │   ├── config.py           ← pydantic-settings
   │   ├── deps.py             ← FastAPI dependencies (db session, repo)
   │   ├── auth_context.py     ← Phase 12-ready hardcoded AuthContext
   │   ├── logging.py          ← structlog setup
   │   ├── middleware.py       ← request ID, X-BSS-Actor/Channel, logging
   │   ├── repository.py       ← async SQLAlchemy queries
   │   ├── routes/
   │   │   ├── __init__.py
   │   │   ├── health.py
   │   │   ├── product_offering.py
   │   │   ├── product_specification.py
   │   │   └── vas.py
   │   └── schemas/
   │       ├── __init__.py
   │       ├── tmf620.py       ← TMF620 Pydantic models
   │       └── vas.py
   └── tests/
       ├── conftest.py
       ├── test_catalog_api.py
       └── test_catalog_repository.py
   ```

2. **Repository pattern (not service classes for read-mostly services):**
   ```python
   class CatalogRepository:
       def __init__(self, session: AsyncSession): ...
       async def list_offerings(self, *, lifecycle_status: str | None = None, limit: int = 20, offset: int = 0) -> list[ProductOffering]: ...
       async def get_offering(self, offering_id: UUID) -> ProductOffering | None: ...
   ```

3. **TMF mapping in a dedicated module** — never mix DB models and TMF schemas. Always map at the route layer:
   ```python
   def to_tmf620_offering(model: ProductOffering) -> Tmf620ProductOffering: ...
   ```

4. **Request ID propagation** — every log line includes `request_id`. Every outgoing HTTP call (later phases) includes the header.

5. **Settings as singletons via dependency injection**, never imported globally.

6. **Tests use testcontainers postgres**, not SQLite. The whole point is to test against real Postgres with the real schema.

7. **Run port:** `8002` (per `ARCHITECTURE.md`)

## Out of scope

- Write endpoints (POST/PATCH/DELETE) — catalog is read-only in v0.1, seeded via `bss-seed`
- Authentication / authorization — single-tenant, no auth in v0.x
- Rate limiting
- Caching (Redis, in-memory)
- TMF eventing webhook subscriptions (TMF620 has them, we skip for v0.1)
- OpenTelemetry — Phase 9
- Pagination beyond limit/offset

## Verification

```bash
make up
make migrate
make seed
docker compose up -d catalog
sleep 3

curl -s localhost:8001/health | jq
# Expected: { "status": "ok", "service": "catalog", "version": "0.1.0" }

curl -s localhost:8001/tmf-api/productCatalogManagement/v4/productOffering | jq
# Expected: array of 3 offerings (PLAN_S, PLAN_M, PLAN_L) in TMF620 format
# Must include fields: id, name, lifecycleStatus, productOfferingPrice, etc.

curl -s localhost:8001/tmf-api/productCatalogManagement/v4/productOffering/<id> | jq
# Expected: single offering with full bundle allowance details

curl -s localhost:8001/vas/offering | jq
# Expected: array of 3 VAS offerings

cd services/catalog
uv run pytest -v
# Expected: all tests pass

curl -s localhost:8001/docs
# Expected: OpenAPI docs render
```

## Constraints

- FastAPI + uvicorn, async throughout
- Use the `bss-models` package for SQLAlchemy models — do NOT redefine them
- Pydantic v2
- No business logic in routes — delegate to repository
- No DB queries outside repository
- All logging via `structlog`, never `print()` or stdlib `logging` directly
- Dockerfile uses Python 3.12 slim, multi-stage, runs as non-root UID 1000
- Tests must pass against a clean database, not the seeded dev DB
- Coverage target: every endpoint has a happy-path test and a 404 test

## Stop conditions

Stop and ask if:
- TMF620 spec ambiguity (field types, optional vs required) — surface and ask, do not guess
- Async session management feels awkward — likely means the dependency wiring is wrong, fix before proceeding
- The pattern feels heavy for a read-only service — this is intentional, the weight pays off in Phases 4-6 when we clone it

## Why this phase matters

Every line of code written here will be copied 6 times. A 5% improvement in this phase compounds across the codebase. A bad decision here propagates everywhere. Treat this as the architectural commitment, not the catalog service.
