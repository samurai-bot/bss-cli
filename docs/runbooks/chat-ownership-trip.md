# Investigating an ownership-check trip

> **A trip is P0.** The output trip-wire fired because a chat-surface
> tool returned data that did not belong to the bound customer.
> Server-side policies are the primary boundary; the trip-wire is
> the second line. A trip means a policy missed a case.

## Symptom

* The customer saw a generic "Sorry — I couldn't complete that"
  reply instead of the LLM's intended response.
* `audit.domain_event` has a fresh `interaction.created` row with
  `service_identity="portal_self_serve"` and a body that begins
  `"P0 agent ownership violation on <tool>"` — written by
  `orchestrator.ownership.record_violation` via CRM's
  `log_interaction` auto-log path.
* Structlog at the orchestrator process emits an
  `agent.ownership_violation` event around the same moment.

## Triage queries

```sql
-- All ownership-violation interactions in the last 24h.
SELECT i.id, i.customer_id, i.summary, i.body, i.created_at
FROM crm.interaction i
WHERE i.summary LIKE 'P0 agent ownership violation%'
  AND i.created_at > now() - interval '24 hours'
ORDER BY i.created_at DESC;

-- Match against the actor's owned subscriptions to confirm the
-- canonical tool returned an alien customerId.
SELECT s.id, s.customer_id, s.state
FROM subscription.subscription s
WHERE s.customer_id = '<actor>';
```

In `bss trace`, search for the trace_id stamped on the violation
interaction and follow upstream to the canonical tool's HTTP call.

## Common causes

1. **A new server-side endpoint returns rows by a non-customer
   filter.** Most likely culprit. Check the canonical tool's
   policy file — it should call `check_<resource>_owned_by` (or
   the equivalent customer-id filter) before returning. Add the
   missing check; deploy; re-run the soak.

2. **A new `*.mine` wrapper was added without updating
   `OWNERSHIP_PATHS`.** The trip-wire only checks paths in the
   registry — but the startup self-check
   (`tools/_profiles.validate_profiles`) catches a missing entry
   at import time. If you got past startup, this is unlikely; if
   you somehow disabled the self-check, re-enable.

3. **Path syntax mismatch.** The canonical tool changed its
   response shape (e.g., renamed `customerId` to `customer_id`
   on a list element). Update the `OWNERSHIP_PATHS` entry to
   walk the new path. Add a regression test asserting the new
   shape against a planted-bad payload.

## Remediation order

1. **Stop the bleed.** If the bug is reproducible, disable the
   `customer_self_serve` profile temporarily by removing the
   offending tool from `TOOL_PROFILES["customer_self_serve"]` and
   restarting the orchestrator. The chat surface still works
   without that tool.

2. **Find the policy gap.** The trip-wire's audit row has the
   tool name, the path that resolved to an alien value, and the
   value itself. Trace upstream — the canonical tool's path is
   in `tools/<domain>.py`; its policy is in
   `services/<domain>/app/policies/`.

3. **Add the missing policy + test.** Server-side test asserting
   the cross-customer call is rejected. Wrapper-side test
   asserting the trip-wire fires on a planted bad payload.

4. **Re-soak.** A trip in the 14-day soak is a doctrine block —
   re-run with the fix, confirm zero trips before tagging.

## What NOT to do

* **Don't widen `OWNERSHIP_PATHS`** to silence the trip. The
  trip is telling you a policy is wrong; an empty path list
  means "this tool's response carries no customer-bound fields
  by contract" and using it as a mute is exactly the wrong move.
* **Don't disable the trip-wire.** The whole point is to fail
  loudly when policies miss a case. A muted trip-wire that ships
  cross-customer data once is worse than a trip-wire that errs
  on the side of generic safety replies.
