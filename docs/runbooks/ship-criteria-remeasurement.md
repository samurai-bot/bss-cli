# Re-measuring ship criteria

> Motto principle 6 says "lightweight is measurable" — under 4 GB RAM, under 30s cold start, under 50ms p99 internal API. These numbers drift as the stack grows (OTel, middleware, portals each add cost). Every minor version re-measures and updates `SHIP_CRITERIA.md` with the v0.X numbers. **Update the doc to reflect reality**, even if the new number is worse than the previous one. Honesty over aspiration.

## When to re-measure

- Before tagging any minor version (`v0.X.0`)
- After any change that touches: middleware stack, container layer, OTel SDK version, portal count, base image
- Whenever `SHIP_CRITERIA.md` is more than one minor version behind the tagged HEAD

## Three measurements

### 1. Idle RAM (bundled mode)

```bash
# Fresh start with infra
docker compose -f docker-compose.yml -f docker-compose.infra.yml down -v
docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d --wait

# Wait 5 minutes for idle steady state — services finish initialization
# and OTel batch processors quiesce
sleep 300

# Measure
docker stats --no-stream
```

Sum the `MEM USAGE` column across all bss-cli-* containers + postgres + rabbitmq + metabase + jaeger. That's the bundled-mode total.

For BYOI mode (services + portals only), filter out infra:

```bash
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}" | grep -E 'bss-cli-(catalog|crm|payment|com|som|subscription|mediation|rating|provisioning|portal)'
```

### 2. Cold start

```bash
# Hard restart from scratch
docker compose -f docker-compose.yml -f docker-compose.infra.yml down -v

time docker compose -f docker-compose.yml -f docker-compose.infra.yml up -d --wait
```

`--wait` blocks until every container's healthcheck passes. The wall clock is the cold-start number. Run three times and take the median — first run pulls images, subsequent runs measure container startup only.

### 3. p99 internal API latency

```bash
# Make sure the stack is up (don't just-restarted it for measurement #2)
make migrate
make seed

# Run the deterministic hero scenario 10 times
for i in $(seq 1 10); do
  uv run bss scenario run scenarios/customer_signup_and_exhaust.yaml > /dev/null
done

# Pull the spans from Jaeger via bss trace
# (the scenario's order IDs are sequential — adjust the range)
for ord in $(seq -f 'ORD-%04g' 1 10); do
  uv run bss trace for-order "$ord" --json > /tmp/trace_$ord.json 2>/dev/null
done

# Parse internal HTTP span durations and compute p99
# (One-liner; for a real measurement script see analyze_p99.py in PR 5)
python -c "
import json, glob
durs = []
for f in glob.glob('/tmp/trace_ORD-*.json'):
    spans = json.load(open(f))
    for s in spans:
        if s.get('kind') == 'server' and s.get('attributes', {}).get('http.route'):
            durs.append(s['duration_ms'])
durs.sort()
n = len(durs)
print(f'samples={n}, p50={durs[n//2]:.1f}ms, p99={durs[int(n*0.99)]:.1f}ms')
"
```

The `p99` value is the criterion. Hero-scenario load is a fair proxy because it exercises the activation hot path (the most-called set of internal endpoints). For deeper measurement, swap to a dedicated load-gen scenario.

## Recording the result

Update `SHIP_CRITERIA.md` with the v0.X numbers in a labeled subsection:

```markdown
## Runtime (v0.X measured YYYY-MM-DD)

- [x] All containers report healthy within **N seconds** of cold start (vs <30s motto target)
- [x] Total resident memory across containers is **N GB** at idle (vs <4 GB motto target)
- [x] p99 internal API latency is **N ms** (vs <50 ms motto target)
```

If a number exceeds its motto target, add a note explaining why (and either fix it before the tag, or open a DECISIONS entry justifying the new number). Do not silently raise the ceiling.

## Reproducibility

These commands are the canonical recipe — a reviewer cloning the repo at a tag should be able to re-run them and get the same numbers (within model + system variance). Pin the run-environment specifics (host CPU, RAM, Docker version) in the SHIP_CRITERIA entry if numbers are sensitive.
