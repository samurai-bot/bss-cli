# Rotating BSS API tokens

> **Audience:** operators running BSS-CLI v0.3+ in any deployment mode (local dev, BYOI, all-in-one). API tokens are the only credentials that gate every BSS service's HTTP surface.

## Token model (v0.3 → v0.9)

- **v0.3** introduced a single `BSS_API_TOKEN` carried by every internal caller (orchestrator, CSR, scenarios). Every BSS service validates it.
- **v0.9** splits the perimeter into named tokens. Each external-facing surface gets its own. The middleware loads a `TokenMap` from env vars matching `BSS_API_TOKEN` and `BSS_<NAME>_API_TOKEN`; identity is derived from the env-var name (`BSS_PORTAL_API_TOKEN` → `"portal"` — wired up as `"portal_self_serve"` from the portal client side).
- A successful match attaches `service_identity` to the request. Audit, structlog, and OTel spans carry it. Operators can answer "which surface initiated this?" by reading the audit log.

A leaked named token now rotates independently of the orchestrator's token. Same restart-based procedure; smaller blast radius.

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

---

## Rotating BSS_PORTAL_API_TOKEN (v0.9+)

The self-serve portal carries its own named token. Rotating it does **not** require restarting the BSS services or the orchestrator/CSR — only the portal container needs the new value, because only the portal carries this token outbound. The BSS services' middleware loads the token map at startup; if the rotated value is in their env too (it should be), they'll accept it without restart of their own only if you happened to leave the new value already loaded — otherwise the portal's outbound calls will 401 until the BSS services pick up the new map.

```bash
# 1. Generate a new portal token.
NEW_PORTAL_TOKEN=$(openssl rand -hex 32)

# 2. Update .env on every host that loads it (services host + portal host).
sed -i.bak "s/^BSS_PORTAL_API_TOKEN=.*/BSS_PORTAL_API_TOKEN=$NEW_PORTAL_TOKEN/" .env

# 3. Restart containers that need the new value.
#    Order matters: services first (so they accept the new token in
#    their TokenMap), then the portal (so its outbound calls use the
#    new token).
docker compose restart catalog crm com som payment subscription mediation rating provisioning-sim
docker compose restart portal-self-serve

# 4. Verify the portal still functions end-to-end.
curl -i http://localhost:9001/welcome   # 200 (public route)
# Then walk a customer signup through the UI; the activation page must render.

# 5. Shred .env.bak.
shred -u .env.bak
```

The orchestrator and CSR console are **unaffected** — they keep running with `BSS_API_TOKEN`.

## Detecting a leaked named token

The blast-radius point of named tokens is that anomalous activity attributed to one identity is visible without correlating across surfaces. Three queries:

### 1. Audit rows by service_identity over the past 24h

```sql
SELECT service_identity, COUNT(*) AS events, MAX(occurred_at) AS last
  FROM audit.domain_event
 WHERE occurred_at > NOW() - INTERVAL '24 hours'
 GROUP BY service_identity
 ORDER BY events DESC;
```

Unexpected identities or unusual ratios (e.g., portal_self_serve writing 100× normal) are the leak signal.

### 2. Failed-auth log lines

The perimeter middleware logs every 401 at INFO with `auth.401` event. Throttled to one per `(remote_addr, path)` per 60s, so a sustained probe shows up as repeated lines after the throttle window resets.

```bash
docker compose logs catalog crm | grep -E "auth\.401|reason=(missing|wrong)"
```

A spike before a successful authenticated write often precedes a token-guess that landed.

### 3. Jaeger / `bss trace` filter by identity

The OTel server span carries `bss.service.identity` per request (v0.9+). In Jaeger UI, filter by tag `bss.service.identity=portal_self_serve` to scope the search to portal-initiated traces. The `bss trace` CLI swimlane shows the column inline.

## Adding a new named token

The pattern is `BSS_<NAME>_API_TOKEN` (uppercase, where `<NAME>` doesn't contain `_API_TOKEN`). Identity at the receiving side is `<name>` lowercased.

1. Generate a 32-byte hex token: `openssl rand -hex 32`.
2. Add it to `.env` on every host that loads BSS-CLI's perimeter middleware (i.e., every BSS service container and any portal/partner client that will use it).
3. Restart the BSS services so the TokenMap loader picks it up: `docker compose restart catalog crm com som payment subscription mediation rating provisioning-sim`.
4. Wire the consuming surface (portal, partner client) to load its token from the same env var via `NamedTokenAuthProvider("<identity>", "BSS_<NAME>_API_TOKEN")`.
5. Verify with a one-off authenticated call and an `audit.domain_event` query confirming the new identity appears.

Doctrine: each external-facing surface gets its OWN token. Sharing one named token across surfaces collapses the blast-radius reduction back to v0.3.

## See also

- `phases/V0_3_0.md` — full v0.3 spec (single-token foundation)
- `phases/V0_9_0.md` — full v0.9 spec (named tokens at the perimeter)
- `DECISIONS.md` — `2026-04-23 — v0.3.0 — Shared API token over OAuth for single-operator auth`
- `DECISIONS.md` — `2026-04-26 — v0.9.0 — Named tokens at the perimeter`
- `CLAUDE.md` — Authentication & RBAC readiness section
