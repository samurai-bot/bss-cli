"""Configure OpenTelemetry once per service process.

Call ``configure_telemetry(service_name="crm")`` from each service's
lifespan. Behavior:

- Reads ``BSS_OTEL_*`` env vars via pydantic-settings
- If ``BSS_OTEL_ENABLED=false``, returns ``None`` (no-op for tests)
- Builds a ``TracerProvider`` with ``OTLPSpanExporter`` (HTTP/protobuf)
  and a ``BatchSpanProcessor``
- Installs auto-instrumentors: FastAPI, HTTPX (outbound), AsyncPG
  (via SQLAlchemy), AioPika (MQ publish/consume)
- Idempotent — subsequent calls in the same process return the same
  provider without re-instrumenting
- Never raises into the caller — observability must not gate startup
"""

from __future__ import annotations

import structlog
from opentelemetry import trace
from opentelemetry.trace import Tracer

from .config import Settings

# Heavy instrumentation imports happen lazily inside configure_telemetry().
# This keeps `import bss_telemetry` light enough that the semconv and
# propagation modules can be exercised in unit tests without pulling in
# fastapi / httpx / asyncpg / aio_pika.

log = structlog.get_logger(__name__)

_INSTALLED = False


def configure_telemetry(service_name: str):  # noqa: ANN201 — return type lazy-imported
    """Bootstrap OTel tracing for one service process.

    Returns the TracerProvider on success, ``None`` if telemetry is
    disabled or setup failed. Idempotent within a process.
    """
    global _INSTALLED
    # Heavy SDK imports — only loaded if/when this function actually runs.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    if _INSTALLED:
        provider = trace.get_tracer_provider()
        return provider if isinstance(provider, TracerProvider) else None

    try:
        settings = Settings()
    except Exception as exc:  # noqa: BLE001 — observability never crashes startup
        log.warning("telemetry.config_failed", error=str(exc), service=service_name)
        _INSTALLED = True
        return None

    if not settings.BSS_OTEL_ENABLED:
        log.info("telemetry.disabled", service=service_name)
        _INSTALLED = True
        return None

    try:
        resource = Resource.create(
            {
                "service.name": f"{settings.BSS_OTEL_SERVICE_NAME_PREFIX}-{service_name}",
                "service.version": settings.BSS_OTEL_SERVICE_VERSION,
            }
        )
        provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(settings.BSS_OTEL_SAMPLING_RATIO),
        )
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.BSS_OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/')}/v1/traces",
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
        AsyncPGInstrumentor().instrument()
        AioPikaInstrumentor().instrument()

        log.info(
            "telemetry.configured",
            service=service_name,
            endpoint=settings.BSS_OTEL_EXPORTER_OTLP_ENDPOINT,
            sampling_ratio=settings.BSS_OTEL_SAMPLING_RATIO,
        )
        _INSTALLED = True
        return provider
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry.setup_failed", error=str(exc), service=service_name)
        _INSTALLED = True
        return None


def tracer(name: str) -> Tracer:
    """Get a Tracer for manual span creation.

    Reserved for the 3 documented manual-span sites (V0_2_0.md §2a).
    All other instrumentation is automatic.
    """
    return trace.get_tracer(name)
