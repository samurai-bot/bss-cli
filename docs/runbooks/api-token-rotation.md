# Rotating BSS_API_TOKEN

> **Audience:** operators running BSS-CLI v0.3+ in any deployment mode (local dev, BYOI, all-in-one). The token is the only credential that gates every BSS service's HTTP surface.

## When to rotate

- Quarterly (calendar-driven good hygiene).
- Suspected leak (CI logs, shared screenshots, accidental commit).
- Personnel change (someone with .env access is no longer trusted).
- Pre-tag of a public release (so the demo token never touches production).

## Procedure (restart-based, ~60s)

v0.3 does NOT support zero-downtime rotation. A rolling strategy ("services accept current OR next token for a window") is a real auth system feature deferred to Phase 12. For single-operator single-tenant deployments, a 60-second compose restart is acceptable.

```bash
# 1. Generate a new token (64 hex chars, ≥32 required)
NEW_TOKEN=$(openssl rand -hex 32)
echo "$NEW_TOKEN"

# 2. Update .env on every host that runs BSS-CLI components:
#    - the services host (where docker compose up runs)
#    - the CLI/orchestrator host (where `bss ...` is invoked)
#    - any portal host (post-v0.4)
#    Both client and server must agree on the same value.
sed -i.bak "s/^BSS_API_TOKEN=.*/BSS_API_TOKEN=$NEW_TOKEN/" .env

# 3. Restart services to pick up the new token at startup.
#    The lifespan validator runs validate_api_token_present()
#    and reads the new value via pydantic-settings.
docker compose down
docker compose up -d

# 4. Verify
curl -i http://localhost:8002/health  # 200 (exempt; no token needed)
curl -i http://localhost:8002/tmf-api/customerManagement/v4/customer  # 401 (no token)
curl -i -H "X-BSS-API-Token: $NEW_TOKEN" \
    http://localhost:8002/tmf-api/customerManagement/v4/customer  # 200

# 5. Shred the .env.bak left behind by sed
shred -u .env.bak  # or rm -P .env.bak on macOS
```

## What if I lose the token?

Generate a new one (Step 1 above), restart everything (Steps 3-4). The "old token" is a 32-char string in your `.env` — there's no token store on the server, no JWT issuance log, no DB row. It's just an env var.

## What if a CLI invocation in another shell still has the old token cached?

It doesn't — the CLI reads `BSS_API_TOKEN` per process via `bss_middleware.api_token()`. Open a fresh shell and the new value applies.

## What if the token leaks into a log?

`structlog`'s `redact_sensitive` processor already redacts any key containing `"token"`. The middleware itself never logs the token (the 401 error message says `"invalid API token"`, never echoing the provided value). If you spot a log line containing the actual hex value, that's a bug — file it, then rotate immediately.

## Why no zero-downtime rotation in v0.3?

- Rolling rotation needs services to accept TWO valid tokens during a window. That's auth-system-shaped: token registry, expiry tracking, validity logic per request.
- v0.3 is "the smallest possible auth story". Adding rolling rotation puts us on the path to rebuilding Phase 12 piecemeal — which is exactly what the v0.3 design rejects.
- For single-operator deployments, 60 seconds of downtime to restart compose is fine. If your deployment can't tolerate that, you needed Phase 12 already.

## See also

- `phases/V0_3_0.md` — full v0.3 spec
- `DECISIONS.md` — `2026-04-23 — v0.3.0 — Shared API token over OAuth for single-operator auth`
- `CLAUDE.md` — Authentication & RBAC readiness section
