FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv

COPY packages/ packages/
COPY services/crm/ services/crm/

WORKDIR /build/services/crm
# In Docker there is no workspace root — switch source from workspace to path
RUN sed -i 's|workspace = true|path = "../../packages/bss-models"|' pyproject.toml \
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
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
