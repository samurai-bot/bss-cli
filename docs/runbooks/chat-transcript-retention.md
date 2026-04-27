# Chat transcript retention

v0.12 stores chat transcripts in `audit.chat_transcript` whenever
`case.open_for_me` runs. The table is append-only. v0.12's policy
is intentionally simple — v1.x can tighten if storage growth
demands.

## Retention rule

* **Active case** (state != `closed`): keep the transcript
  indefinitely. Legal hold is the dominant concern; storage is
  cheap.
* **Closed case + 90 days elapsed**: archive the transcript
  body. The hash row remains so the case still resolves to a
  recognisable transcript reference; the body is replaced with
  a placeholder string.

## Archive job (manual; v0.12)

There is no scheduled archive job in v0.12 — the operator runs
the archive admin command on a cadence (monthly during the
soak; quarterly thereafter, until volume justifies automation):

```bash
# Dry run — list what would be archived.
PSQL_URL="postgresql://bss:bss_password@<host>:5432/bss"
psql "$PSQL_URL" -c "
SELECT t.hash, t.customer_id, t.recorded_at
FROM audit.chat_transcript t
JOIN crm.case c ON c.chat_transcript_hash = t.hash
WHERE c.state = 'closed'
  AND c.closed_at < now() - interval '90 days'
ORDER BY t.recorded_at;
"

# Archive (replace body with placeholder).
psql "$PSQL_URL" -c "
UPDATE audit.chat_transcript t
SET body = '[archived per v0.12 retention runbook on ' || now()::text || ']'
FROM crm.case c
WHERE c.chat_transcript_hash = t.hash
  AND c.state = 'closed'
  AND c.closed_at < now() - interval '90 days'
  AND t.body NOT LIKE '[archived %';
"
```

The hash PK is preserved so the v0.5 case-detail page's transcript
panel still resolves the row — it just renders the placeholder.

## When to tighten

If the soak (or production) reveals transcript growth materially
above expectation (e.g., > 1GB for a 14-day window when a
typical transcript is ~2KB), tighten the retention window
**within v0.12** rather than pushing it to v1.0. The runbook is
a v0.12 deliverable; v1.0 inherits whatever policy v0.12 ends
up with.

Possible tightenings:

* Shorten the 90-day window to 30 days for closed cases.
* Add a per-category retention rule (e.g., regulator_complaint
  cases retain longer than `other`).
* Hash-truncate the body to N kilobytes after archive (vs full
  placeholder).

## What NOT to do

* **Don't delete the hash row.** The case row's
  `chat_transcript_hash` would dangle; the v0.5 case-detail page
  renders "Transcript is no longer retrievable" but knowing the
  hash existed is auditable signal. Replace the body, keep the
  row.
* **Don't archive transcripts on open cases.** Even if the case
  is 90 days old, an open case has an active need for the
  transcript. The 90-day window is closed-at-relative.
* **Don't skip the audit trail.** When archiving, write a CRM
  interaction on each affected customer's record summarising
  "transcript archived per retention policy" with the case id.
  This is the operator's accountability marker.
