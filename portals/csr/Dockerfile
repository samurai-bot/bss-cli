FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv

COPY packages/ packages/
COPY orchestrator/ orchestrator/
COPY portals/csr/ portals/csr/

# Rewrite workspace refs in packages/*/pyproject.toml. Two passes:
# 1) bss-orchestrator lives at /build/orchestrator, NOT under packages/.
# 2) every other bss-* lives in a sibling dir under packages/.
# Regex allows hyphenated names (bss-portal-ui).
RUN for p in packages/*/pyproject.toml; do \
      sed -i -E 's|bss-orchestrator = \{ workspace = true \}|bss-orchestrator = { path = "../../orchestrator" }|g' "$p"; \
      sed -i -E 's|(bss-[a-z][a-z-]*) = \{ workspace = true \}|\1 = { path = "../\1" }|g' "$p"; \
    done

# Orchestrator has workspace deps too — rewrite before portal install.
RUN sed -i -E 's|(bss-[a-z][a-z-]*) = \{ workspace = true \}|\1 = { path = "../packages/\1" }|g' orchestrator/pyproject.toml

WORKDIR /build/portals/csr
# Portal references ../../packages/* and ../../orchestrator — rewrite both.
RUN sed -i -E 's|(bss-[a-z][a-z-]*) = \{ workspace = true \}|\1 = { path = "../../packages/\1" }|g' pyproject.toml \
    && sed -i 's|bss-orchestrator = { path = "../../packages/bss-orchestrator" }|bss-orchestrator = { path = "../../orchestrator" }|' pyproject.toml \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python .

FROM python:3.12-slim AS runtime
RUN useradd -m -u 1000 bss && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder --chown=bss:bss /app/.venv /app/.venv
WORKDIR /app
USER bss
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "bss_csr.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
