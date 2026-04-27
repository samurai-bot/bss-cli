# Post-login self-serve ops runbook

> v0.10+. Common operational diagnostics for the eight post-login direct-API surfaces (`/`, `/top-up`, `/payment-methods*`, `/esim/<id>`, `/subscription/<id>/cancel`, `/profile/contact*`, `/billing/history`, `/plan/change*`). Per `phases/V0_10_0.md` Track 11.3.

## Diagnosing a stuck plan change

**Symptom:** customer scheduled a plan switch on `/plan/change`. The dashboard kept showing the pending banner past the renewal date. New plan never took effect.

**What to check, in order:**

1. **Confirm the schedule landed in the BSS.**

   ```sql
   SELECT id, offering_id, pending_offering_id, pending_offering_price_id,
          pending_effective_at, current_period_end, state
   FROM   subscription.subscription
   WHERE  id = 'SUB-XXX';
   ```

   `pending_offering_id` should be set; `pending_effective_at` should equal `current_period_end` at the time the schedule landed.

2. **Confirm the renewal was attempted.**

   ```sql
   SELECT * FROM audit.domain_event
   WHERE  aggregate_id = 'SUB-XXX'
     AND  event_type IN (
            'subscription.renewed',
            'subscription.renew_attempted',
            'subscription.renew_failed'
          )
   ORDER BY occurred_at DESC LIMIT 10;
   ```

   The most common stuck-pending cause is a renewal payment failure — the subscription transitions `active → pending_renewal_failed`, the pending plan-change fields stay set, and the customer's bundle stops being topped up. Look for `subscription.renew_failed` events.

3. **If renewal payment failed:** the customer must add a working COF and either wait for the next renewal attempt or use `subscription.renew` (CSR-side) to retry. The pending plan change applies on the renewal that succeeds — it's not lost.

4. **If renewal didn't run at all:** check the renewal scheduler (clock-driven; in v0.10 it's still cron-style not event-driven). Confirm `bss_clock.now()` has actually advanced past `current_period_end`.

5. **The portal-side audit row** for the schedule is in `portal_auth.portal_action`:

   ```sql
   SELECT ts, action, success, error_rule, ip
   FROM   portal_auth.portal_action
   WHERE  customer_id = 'CUST-XXX'
     AND  action = 'plan_change_schedule'
   ORDER BY ts DESC LIMIT 5;
   ```

   `success=true` rows are what the customer sees as "scheduled"; `success=false` with an `error_rule` tells you the schedule never landed.

## Customer can't add a card

**Symptom:** customer reports they tried `/payment-methods/add` but got an error and no card on file.

**Decision tree:**

1. **Was the form submission rejected by the v0.10 client-side tokenizer?**

   The `/payment-methods/add` route does its own tokenization (mirroring the orchestrator pattern) before calling the BSS. If the card number contains `FAIL` (e.g. `4111111111FAILED`) the tokenizer mints a `tok_FAIL_*` token; if it contains `DECLINE` it mints `tok_DECLINE_*`. The mock payment provider then declines the create. This is dev/test behaviour and is expected.

   ```sql
   SELECT ts, error_rule, ip, user_agent
   FROM   portal_auth.portal_action
   WHERE  customer_id = 'CUST-XXX'
     AND  action = 'payment_method_add'
     AND  success = false
   ORDER BY ts DESC LIMIT 5;
   ```

   `error_rule = 'policy.payment.method.invalid_card'` → the digits weren't valid (non-digit input or too few digits).
   `error_rule = 'policy.payment.method.declined'` → the mock provider declined; check whether the test card embedded `DECLINE`.

2. **Did the BSS-side policy reject it?** Most likely culprits:

   * `policy.payment.method.duplicate` — the card token is already on file. v0.10 mock tokenizer mints fresh UUIDs, so this should not fire on a real fresh add — if it does, suspect the test seeded the same `tok_*` value twice.
   * `policy.customer.contact.not_found` — the `customer_id` from the session doesn't match an existing CRM customer. Should be impossible after `requires_linked_customer` resolves; investigate identity ↔ customer linkage in `portal_auth.identity`.

3. **Step-up failure?** The portal redirects to `/auth/step-up?action=payment_method_add` on a missing grant. If the customer keeps getting bounced, check `portal_auth.login_attempt` for the rate limiter:

   ```sql
   SELECT * FROM portal_auth.login_attempt
   WHERE  email = 'customer@example.com'
     AND  ts > now() - interval '1 hour'
   ORDER BY ts DESC;
   ```

   Repeated `outcome='rate_limited'` rows = the customer hit the per-email cap; tell them to wait and try again.

## Customer claims they didn't authorise X

**Symptom:** customer disputes a write that came through the self-serve portal — "I didn't cancel my line" / "I didn't switch plans" / "I didn't change my email".

**The portal-side audit table** `portal_auth.portal_action` is the forensic record:

```sql
SELECT ts, action, route, method, success, step_up_consumed,
       error_rule, ip, user_agent
FROM   portal_auth.portal_action
WHERE  customer_id = 'CUST-XXX'
  AND  ts > now() - interval '30 days'
ORDER BY ts DESC;
```

Read this together with `audit.domain_event` (the BSS-side change record) and `portal_auth.session` (the session the action ran under):

* If a row has `success=true` and `step_up_consumed=true`, the action *was* authorised — customer entered an OTP from their email mid-flow. Ask the customer whether they shared their email account or were near a logged-in device.

* If a row has `success=true` and `step_up_consumed=false`, the action ran without a fresh step-up grant. v0.10 only one of these legitimately exists (`email_change_verify` — the OTP itself is the step-up, no separate grant cookie). Anything else with `step_up_consumed=false` is a bug to investigate.

* Cross-reference the IP / user-agent against the customer's normal session pattern. The session row carries the same IP/UA at `issued_at`:

  ```sql
  SELECT s.id, s.issued_at, s.ip, s.user_agent
  FROM   portal_auth.session s
  JOIN   portal_auth.identity i ON i.id = s.identity_id
  WHERE  i.customer_id = 'CUST-XXX'
    AND  s.issued_at > now() - interval '30 days'
  ORDER BY s.issued_at DESC;
  ```

  Sessions issued from a wildly different IP are the strongest signal of an unauthorised actor.

* The step-up OTP that authorised the action is in `portal_auth.login_token` — look for `kind='step_up_grant'`, `action_label='<the action>'`, `consumed_at` near the disputed timestamp. The OTP itself is hashed, but the issuance timestamp + consumption timestamp + IP/UA on the session bracket the event tightly.

If the audit shows the action *was* authorised from the customer's session but the customer maintains they didn't do it, the conversation moves to "your account was compromised, let's force-revoke all sessions and change the email." That's a CSR ticket, not a self-serve flow.

## Email-change stuck pending

**Symptom:** customer started an email change on `/profile/contact` but never received the OTP at the new email, or the verify step keeps failing.

```sql
SELECT id, identity_id, new_email, status, expires_at, consumed_at,
       issued_at, ip, user_agent
FROM   portal_auth.email_change_pending
WHERE  identity_id = (SELECT id FROM portal_auth.identity
                       WHERE  customer_id = 'CUST-XXX'
                       ORDER BY created_at DESC LIMIT 1)
ORDER BY issued_at DESC LIMIT 5;
```

* `status='pending'` + `expires_at > now()` — the OTP is still valid; check the email adapter (dev mailbox or SMTP gateway) for delivery.
* `status='pending'` + `expires_at <= now()` — the row is stale; the verify route will treat it as expired and return `policy.customer.contact_medium.expired`. Tell the customer to restart from `/profile/contact`.
* `status='cancelled'` — the customer (or an admin) explicitly cancelled. No further action needed.
* `status='consumed'` + `consumed_at` set — the change went through. The customer's `crm.contact_medium` row + `portal_auth.identity.email` should both reflect the new value.

The cross-schema atomicity of the verify step is documented in DECISIONS 2026-04-27 (v0.10 PR 8). If the two tables are out of sync — e.g. CRM has the new email but `portal_auth.identity.email` still has the old one — that is a bug, not a stuck-flow. Open an incident; the rollback test (`test_email_change_verify_rolls_back_on_partial_failure`) is supposed to make that combination impossible.
