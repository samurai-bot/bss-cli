# Portal authentication — operations runbook (v0.8)

Covers the self-serve portal's email-based login. CSR console is unaffected — it stays on its v0.5 stub-cookie pattern until Phase 12.

The library is `packages/bss-portal-auth`. The schema is `portal_auth` (migration `0008_v080_portal_auth`). Server pepper comes from the `BSS_PORTAL_TOKEN_PEPPER` env. Email delivery uses `LoggingEmailAdapter` (writes to `BSS_PORTAL_DEV_MAILBOX_PATH`) in dev / staging; v1.0 swaps in real SMTP.

## 1. Generating the token pepper

The pepper is the HMAC key for every OTP, magic-link, and step-up grant the portal stores. Without it (or with the `changeme` sentinel) the portal refuses to start.

```bash
openssl rand -hex 32
```

Write the value to `.env` as `BSS_PORTAL_TOKEN_PEPPER=...`. Do not commit. Length must be ≥32 characters; `validate_pepper_present()` enforces this at portal startup.

## 2. Rotating the pepper

Pepper rotation invalidates **every in-flight login token**. That's an acceptable trade for a real MVNO — at most a 15-minute outage of unverified login codes, no impact on already-established sessions (those are server-side rows; their cookie ids don't reference the pepper).

Procedure:

1. Generate the new pepper (`openssl rand -hex 32`).
2. Replace `BSS_PORTAL_TOKEN_PEPPER` in `.env`.
3. **Force-recreate** the portal so the new `.env` is re-read at create-time:
   ```bash
   docker compose up -d --force-recreate portal-self-serve
   ```
   `docker compose up -d` alone keeps the existing container if image +
   compose config hash haven't changed; an env-only edit doesn't trip a
   recreate, and the running container will keep its old baked-in env.
4. Verify: tail the portal logs for `portal_auth.pepper.validated length=64`,
   then `curl -sf http://localhost:9001/health`.

Same rule applies the **first time** you set the pepper after pulling
v0.8 — the portal container brought up before the pepper landed in
`.env` will crash-loop on the unset guard. Force-recreate clears it.

Existing customer sessions remain valid because the cookie value is just the `session` row id; only login-token verification (start → verify) is affected. Customers with active sessions don't notice. Customers mid-login (between "I clicked send-code" and "I entered the OTP") need to start over.

## 3. Cleaning up unverified identities

The schema lets visitors create an `identity` row with `status='unverified'` if they enter their email but never verify. Over time these accumulate. The cleanup is a periodic admin task — there is no automatic GC in v0.8.

```bash
docker compose exec postgres psql -U bss -d bss -c "
  DELETE FROM portal_auth.identity
  WHERE status = 'unverified'
    AND created_at < NOW() - INTERVAL '30 days';
"
```

Cascade-deletes the `login_token` rows that referenced these identities. `login_attempt` rows are untouched (audit log is append-only and retained per regulatory policy).

## 4. Investigating a suspected brute-force attempt

`login_attempt` is the audit substrate. Every start / verify / step-up call writes one row.

Suspect IP:

```bash
docker compose exec postgres psql -U bss -d bss -c "
  SELECT outcome, stage, COUNT(*) AS n
  FROM portal_auth.login_attempt
  WHERE ip = '<ip>'
    AND ts > NOW() - INTERVAL '1 hour'
  GROUP BY outcome, stage
  ORDER BY n DESC;
"
```

Suspect email:

```bash
docker compose exec postgres psql -U bss -d bss -c "
  SELECT ts, ip, stage, outcome
  FROM portal_auth.login_attempt
  WHERE email = '<email>'
    AND ts > NOW() - INTERVAL '24 hours'
  ORDER BY ts DESC;
"
```

If you see sustained `wrong_code` or `rate_limited` rows from a single IP, tighten the per-IP cap via `BSS_PORTAL_LOGIN_PER_IP_MAX` and `BSS_PORTAL_LOGIN_PER_IP_WINDOW_S` in `.env` and restart the portal. The defaults (10 per hour) suit a home-broadband demo; production-grade caps are a v1.0 hardening item alongside captcha / WAF.

## 5. Local dev mailbox

`LoggingEmailAdapter` writes one block per send to `BSS_PORTAL_DEV_MAILBOX_PATH`. In compose the path is bind-mounted to `./.dev-mailbox/portal-mailbox.log` on the host so the scenario runner — which runs from the host — can read OTPs.

Tail in dev:

```bash
tail -f .dev-mailbox/portal-mailbox.log
```

You'll see something like:

```
=== 2026-04-26T09:00:00+00:00 ===
To: ada@example.sg
Subject: Your bss-cli portal login code

OTP: 424242
Magic link: 8jK_Ap6Ye3C7sB1fX0NwQv9x_uG2HmPq

Code expires in 15 minutes.
```

Truncate when noisy:

```bash
: > .dev-mailbox/portal-mailbox.log
```

The structured log only carries `email_domain`, never the OTP / magic-link plaintext. `rg 'log\.(info|debug|warning).*(otp|magic_link|token)' packages/bss-portal-auth/` must stay empty (CI grep guard).

## 6. Forcing a session revocation

If a customer reports their account compromised, revoke every active session under their email:

```bash
docker compose exec postgres psql -U bss -d bss -c "
  UPDATE portal_auth.session s
  SET revoked_at = NOW()
  FROM portal_auth.identity i
  WHERE s.identity_id = i.id
    AND i.email = '<email>'
    AND s.revoked_at IS NULL;
"
```

Their next request to any gated route will fall through to `/auth/login` because `current_session` rejects revoked rows.
