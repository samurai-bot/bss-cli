# Installing Jaeger on a BYOI host

> **Audience:** operators running BSS-CLI in BYOI mode (services on one host, infrastructure on another). For the all-in-one path, Jaeger is already in `docker-compose.infra.yml` — see README "Quick start (all-in-one)".

BSS-CLI v0.2 onward exports OpenTelemetry traces to a Jaeger backend over OTLP/HTTP. In BYOI mode you install Jaeger once on the same host that runs your other infra (typically the box that already hosts Postgres + RabbitMQ — `tech-vm` in the canonical setup) and point every service at it via `BSS_OTEL_EXPORTER_OTLP_ENDPOINT`.

## Recommended: add to the host's existing `docker-compose.yml`

If the BYOI host already manages infra via compose, append a Jaeger service block alongside postgres and rabbitmq:

```yaml
# on tech-vm — append to the existing docker-compose.yml
  jaeger:
    image: jaegertracing/all-in-one:1.65.0
    container_name: jaeger
    restart: unless-stopped
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
      SPAN_STORAGE_TYPE: "memory"
    ports:
      - "4317:4317"   # OTLP/gRPC ingress
      - "4318:4318"   # OTLP/HTTP ingress (services use this)
      - "16686:16686" # Jaeger UI
```

Then on the host:

```bash
docker compose pull jaeger
docker compose up -d jaeger
```

## Alternative: standalone `docker run`

If the BYOI host doesn't use compose for infra:

```bash
docker run -d --name jaeger --restart unless-stopped \
  -e COLLECTOR_OTLP_ENABLED=true \
  -e SPAN_STORAGE_TYPE=memory \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 16686:16686 \
  jaegertracing/all-in-one:1.65.0
```

## Configure services to export to it

On the host running services, edit `.env`:

```bash
BSS_OTEL_ENABLED=true
BSS_OTEL_EXPORTER_OTLP_ENDPOINT=http://tech-vm:4318
```

Restart services to pick up the new endpoint:

```bash
docker compose up -d --force-recreate
```

## Verify

After services are healthy, run a scenario or fire a request:

```bash
bss scenario run scenarios/customer_signup_and_exhaust.yaml
```

Wait ~5 seconds for the batch span exporter to flush, then check:

```bash
# All 9 BSS services should appear
curl -s http://tech-vm:16686/api/services | python3 -m json.tool
```

Expected:

```json
{
  "data": ["bss-catalog", "bss-com", "bss-crm", "bss-mediation",
           "bss-payment", "bss-provisioning-sim", "bss-rating",
           "bss-som", "bss-subscription", "jaeger-all-in-one"],
  "total": 10, ...
}
```

Open the Jaeger UI at `http://tech-vm:16686/` and use the service dropdown to inspect a recent trace.

## Storage trade-off

`SPAN_STORAGE_TYPE=memory` is what the example uses — fine for demo and dev, **lost on container restart**. For a long-running BYOI box that needs persistence:

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.65.0
  environment:
    COLLECTOR_OTLP_ENABLED: "true"
    SPAN_STORAGE_TYPE: "badger"
    BADGER_EPHEMERAL: "false"
    BADGER_DIRECTORY_VALUE: "/badger/data"
    BADGER_DIRECTORY_KEY: "/badger/key"
  volumes:
    - jaeger_data:/badger
  ports: [...]

volumes:
  jaeger_data: {}
```

Production deployments should consider an external storage backend (Cassandra, OpenSearch) — out of scope for v0.2.

## Troubleshooting: spans not appearing in Jaeger

Run through this checklist:

1. **Services healthy?** `docker compose ps` — all 9 services `(healthy)`.
2. **Endpoint reachable from a service container?**
   ```bash
   docker exec bss-cli-crm-1 python -c "
   import socket
   s = socket.create_connection(('tech-vm', 4318), 3)
   print('reachable')
   s.close()
   "
   ```
3. **`BSS_OTEL_ENABLED=true` in .env?** Services log `telemetry.disabled` on startup if false.
4. **`telemetry.configured` in service logs?**
   ```bash
   docker logs bss-cli-crm-1 2>&1 | grep telemetry
   ```
   Should show `event=telemetry.configured`.
5. **Jaeger receiving on 4318?**
   ```bash
   curl -i http://tech-vm:4318/v1/traces
   # 405 Method Not Allowed = listening (POST-only endpoint, healthy)
   # connection refused = Jaeger not running or port not published
   ```
6. **Sampler ratio?** `BSS_OTEL_SAMPLING_RATIO` defaults to 1.0 (sample everything). If lowered for prod, traces get dropped at the source.
7. **Wait the batch interval.** OTel `BatchSpanProcessor` flushes every ~5 seconds. A request fired and queried within 1 second won't show up yet.

If still missing, set the SDK to debug verbose temporarily:

```bash
docker exec bss-cli-crm-1 python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from bss_telemetry.bootstrap import _INSTALLED
print('installed:', _INSTALLED)
"
```

## See also

- `phases/V0_2_0.md` — v0.2.0 spec with the OTel deliverable in full
- `ARCHITECTURE.md` — observability section, deployability matrix
- `DECISIONS.md` — Jaeger vs Tempo rationale
