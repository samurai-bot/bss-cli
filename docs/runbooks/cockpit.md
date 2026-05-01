# Operator cockpit runbook (v0.13)

The v0.13 cockpit is a Postgres-backed Conversation store with two
surfaces:

* **CLI REPL** (`bss`) — canonical. Slash commands + ASCII renderers.
* **Browser veneer** at `localhost:9002/cockpit/<id>` — same store,
  HTML rendering.

Both surfaces drive `astream_once` with the `operator_cockpit` tool
profile and identity; cockpit-driven downstream calls land in
`audit.domain_event` with `service_identity="operator_cockpit"`,
`actor=<settings.actor>`, `channel="cli"|"portal-csr"`.

This runbook covers the routine ops the cockpit's contract requires.

## Resuming a session across surfaces

The whole promise of v0.13: exit `bss`, open a browser, see the same
turns. The store is the single source of truth.

**REPL → browser.**

```bash
$ bss               # opens or resumes the operator's most-recent active session
bss:abc123ef> show me CUST-001
bss:abc123ef> /exit  # leaves session in 'active' state; nothing to flush

# ── then in any browser ────────────────────────────────────
$ open http://localhost:9002/cockpit/SES-20260501-abc123ef
# (or pick the row from /; sessions are listed for the configured actor)
```

The browser thread page renders every prior turn (user / assistant /
tool bubbles) in `created_at` order. Streaming only restarts when the
operator submits a new turn.

**Browser → REPL.**

```bash
$ bss --session SES-20260501-abc123ef
```

`--session` resolves an exact id; missing ids print `Session ... not
found` and exit non-zero. Default `bss` (no flag) resumes the
most-recent active session for `settings.actor`, opening a new one
only if there isn't one.

**`/sessions` lists.** REPL: `/sessions` slash command (Rich table).
Browser: GET `/` (root sessions index). Both filter by
`settings.operator.actor` and order newest-first.

**Tip — naming sessions on open.** `bss --new --label "diagnose
CUST-001"` (REPL) or the "New session" form on `/` (browser). Labels
show up in `/sessions` and on the thread page header.

## Editing OPERATOR.md / settings.toml

Two paths, same store. The mtime hot-reload picks up changes on the
next `current()` call (typically the next cockpit turn or the next
GET `/settings`).

**REPL — slash commands.**

```text
bss:abc123ef> /operator edit
# Opens .bss-cli/OPERATOR.md in $EDITOR (vi default). On close, the
# next current() reload picks up the new content.

bss:abc123ef> /config edit
# Same flow against .bss-cli/settings.toml. Pydantic validation runs
# on the next current() call; a parse error logs a warning and the
# loader keeps serving the prior good view.
```

**Browser — `/settings` page.** Two textareas, two POST buttons. On
save, the v0.13 helpers (`bss_cockpit.write_operator_md` /
`write_settings_toml`) validate before writing — invalid TOML or a
Pydantic schema violation re-renders the page at HTTP 400 with the
parser's diagnostic in-page; the operator's draft round-trips into
the textarea so nothing is lost.

**Recovering from a syntax error.** If you save a `settings.toml`
that the loader rejects, the cockpit keeps serving the prior good
view. Edit `.bss-cli/settings.toml` until `bss_cockpit.config.current()`
reloads cleanly:

```bash
$ uv run python -c "import bss_cockpit; print(bss_cockpit.current().settings)"
```

A clean run prints the validated `CockpitSettings`. A traceback
points at the offending key.

**What's where.**

* `.bss-cli/OPERATOR.md` — operator persona + house rules. Plain
  markdown. Prepended to every cockpit system prompt.
* `.bss-cli/settings.toml` — `[operator] actor`, `[llm] model
  temperature`, `[cockpit] allow_destructive_default`, `[ports]`,
  `[dev_service_urls]`. Pydantic-validated.
* `.bss-cli/*.template` — committed scaffolding. Autobootstrapped on
  first run if the actuals are missing.
* In containers, `BSS_COCKPIT_DIR` overrides the repo-relative path;
  `docker-compose.yml` bind-mounts `./.bss-cli` to `/cockpit-state`
  inside the cockpit container.

## Audit attribution after operator change

`actor` is descriptive, not verified. Changing `settings.toml`'s
`[operator].actor` value affects **future** turns only — old turns
keep their original actor in `cockpit.message` rows + downstream
`audit.domain_event` rows.

**The flow.**

```bash
# 1. Update settings.toml
$ /operator edit       # or open /settings in the browser
# Set [operator].actor = "alice"

# 2. The next cockpit turn picks up the new actor (mtime reload)
$ bss
bss:abc123ef> show me CUST-001
# audit.domain_event row for the resulting customer.get carries
# actor='alice', service_identity='operator_cockpit'.
```

**No process restart required.** The mtime check runs per `current()`
call. The change is visible to both surfaces simultaneously.

**Auditing the change itself.** The settings file edit isn't audited
to `audit.domain_event` (it's operator preference, not a domain
write). If you need a "who changed actor when" record, check
`portals/csr` container logs for `cockpit.settings.toml_saved` /
`cockpit.settings.operator_md_saved` events, or rely on git/rsync if
`.bss-cli/` is in source control on the operator workstation.

## Investigating a cockpit destructive action

The propose-then-`/confirm` flow means every destructive cockpit op
leaves a paper trail across **four** tables:

1. `cockpit.message` — the assistant turn that proposed the action
   (with `tool_calls_json` carrying the propose payload).
2. `cockpit.pending_destructive` — the in-flight propose row,
   pre-`/confirm`. Single-shot — gets DELETE+RETURNINGed when the
   next turn consumes it.
3. `cockpit.message` — the user turn that types `/confirm` (REPL) or
   posts `/cockpit/<id>/confirm` (browser).
4. `audit.domain_event` — the actual downstream domain write
   (`service_identity="operator_cockpit"`, `actor=<settings.actor>`).

**Reconstructing one.**

```sql
-- Find a recent confirmed-destructive turn for one session
SELECT id, role, content, tool_calls_json, created_at
FROM cockpit.message
WHERE session_id = 'SES-20260501-abc123ef'
ORDER BY created_at;

-- The corresponding audit row
SELECT id, occurred_at, actor, service_identity, channel, event_type, payload
FROM audit.domain_event
WHERE service_identity = 'operator_cockpit'
  AND actor = 'ck'
  AND occurred_at > '2026-05-01 10:00:00+08'
ORDER BY occurred_at;
```

The propose → confirm pair is two adjacent assistant + user messages
(or three, when the agent narrates after the operator says
`/confirm`); the audit row's `occurred_at` falls between the
`/confirm` user message and the assistant's reply.

**A propose that never got confirmed** leaves a row in
`cockpit.pending_destructive` with no audit-event correspondent. Sweep
old rows manually (no auto-expiry in v0.13):

```sql
DELETE FROM cockpit.pending_destructive
WHERE proposed_at < now() - interval '7 days';
```

## Rotating BSS_OPERATOR_COCKPIT_API_TOKEN

The cockpit's named token at the v0.9 perimeter. Rotation is
**restart-based**, mirrors `docs/runbooks/api-token-rotation.md`.

**Steps.**

1. Generate a new token:
   ```bash
   openssl rand -hex 32
   ```

2. Edit `.env` to replace `BSS_OPERATOR_COCKPIT_API_TOKEN`.

3. Restart the affected services:
   ```bash
   # Cockpit container reads the env at lifespan boot.
   docker compose up -d portal-csr

   # Every BSS service rebuilds its TokenMap at lifespan boot, so
   # they need to pick up the new value too.
   docker compose restart catalog crm payment subscription com som \
                          provisioning-sim mediation rating
   ```

4. Verify with a smoke turn:
   ```bash
   $ bss
   bss:xxxxxxxx> show the catalog
   # If you see "401 Unauthorized" on a downstream call, the new
   # token didn't propagate. Restart the cockpit + all services.
   ```

**During the gap.** The `NamedTokenAuthProvider` falls back to
`BSS_API_TOKEN` if the cockpit's named env var is unset (staged-rollout
path). During rotation the cockpit briefly carries the default
identity (`"default"` in audit) until the new value lands. If a clean
audit story matters more than zero downtime, bring the cockpit
container down before swapping the env value, then up after both
files are in sync.

**Token doctrine reminders.**

* ≥32 chars, never the sentinel `"changeme"`.
* Each named token must be distinct from every other in the map
  (sharing a token across surfaces defeats blast-radius reduction).
* Tokens never appear in code, logs (the in-memory map is
  HMAC-SHA-256-hashed), or `settings.toml` (which is non-secret).
