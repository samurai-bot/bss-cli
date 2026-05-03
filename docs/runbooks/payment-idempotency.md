# Payment Idempotency (v0.16+)

> **TL;DR.** Every `payment_attempt` row carries an `idempotency_key`
> of the form `ATT-{id}-r{retry_count}`. v0.16 always uses `r0` (one
> attempt = one row = one key). The Stripe SDK passes the key on
> `PaymentIntent.create` so a BSS-side restart of a still-running call
> dedupes at Stripe instead of double-charging the customer.
>
> **The crash-recovery half (re-read the key on restart, send the same
> key, accept the original outcome) is a v1.0 concern and is not yet
> implemented.** v0.16 lays the foundation: persisted key, forensic
> index, runbook. The actual restart-detect logic is held back until
> someone has actually run BSS-CLI in production and we know what
> shapes the crash window takes.

## Why idempotency matters

Stripe's `PaymentIntent.create` is at-least-once from the caller's
perspective: a network blip between BSS and Stripe can leave us
genuinely unsure whether the charge happened. Without an idempotency
key, retrying produces a second charge — the worst possible outcome
for the customer.

With a key, Stripe dedupes server-side: the second call with the same
key returns the original PaymentIntent unchanged. v0.16 always sends
one. v1.0+ will use it correctly across restart boundaries.

## v0.16 contract

```
idempotency_key = f"ATT-{attempt_id}-r{retry_count}"
```

- `attempt_id` is the `payment.payment_attempt.id` (`ATT-1234`, etc.)
- `retry_count` is always `0` in v0.16 (one attempt row → one key)

The key is computed at row creation in `PaymentService.charge` and
recorded on the row's `idempotency_key` column. The Stripe adapter
passes it on every `PaymentIntent.create` call.

## What v1.0 will add (planned, not implemented)

Two distinct retry shapes need different semantics:

### 1. BSS-crash-restart retry — REUSE the key

Scenario: BSS sends `PaymentIntent.create` with `ATT-1234-r0`. Stripe
processes it and charges the card. The TLS connection drops before
Stripe's response reaches BSS. BSS crashes; pod restarts; row is in
`status='charging'` with no `gateway_ref` recorded.

Correct behavior: re-read the recorded `idempotency_key=ATT-1234-r0`
from the row, send the same key to Stripe. Stripe returns the original
PaymentIntent. BSS records the outcome on the existing row. **No
double-charge.**

Detection: row exists with `status='charging'` and a recorded
`idempotency_key`. The current `PaymentService.charge` does NOT have
this branch — it always creates a new row at the top.

### 2. User-initiated UI retry — NEW key

Scenario: BSS sent `PaymentIntent.create` with `ATT-1234-r0`. Stripe
declined the card. The portal showed "card declined; try again". The
customer fixes their card and clicks "Pay" again, intentionally
retrying.

Correct behavior: a NEW `payment_attempt` row is created (`ATT-1235`),
with a NEW key (`ATT-1235-r0`). Stripe sees a fresh charge, processes
it independently, ideally approves this one. **Fresh charge attempt,
not a dedupe.**

Detection: a new row was created (the user re-clicked Pay).

### Why r{retry_count}

The `r0` suffix is forward-compatible. If v1.0 ships a server-side
crash-recovery retry that escalates to a "fresh attempt within the
same row", the suffix increments. The shape stays parseable so
`bss external-calls --idempotency-key ATT-1234-rN` always works.

## Forensic queries

```bash
# Find every Stripe call for a specific attempt:
bss external-calls --idempotency-key ATT-1234-r0

# Find every attempt for a specific Stripe PaymentIntent:
psql -c "SELECT id, status, idempotency_key FROM payment.payment_attempt
         WHERE provider_call_id = 'pi_3TSod8J6V9NGq4GX1yVAfX6Y';"
```

The partial index `ix_payment_attempt_idempotency_key` (created in
migration 0018) makes the first query cheap.

## What can go wrong (and how to recognize it)

- **Same key on user-initiated retry → silent double-charge protection
  hides a real bug.** v0.16's "always r0" never trips this in
  practice (each retry is a new row), but a v1.0 implementation that
  shares keys across rows would. Symptom: customer reports a single
  failed-then-succeeded charge sequence; Stripe shows only one
  PaymentIntent. Look at `payment.payment_attempt` row count for the
  customer in the same minute; if there are two rows but only one
  Stripe call, the keys collided.
- **Fresh key on crash restart → silent double-charge.** The exact
  v1.0 hazard. v0.16 doesn't ship the crash-recovery branch at all,
  so this can only happen if a future patch introduces it incorrectly.
  Symptom: two `payment_attempt` rows for what was logically one
  attempt; two PaymentIntents at Stripe; customer charged twice.
  Always check Stripe dashboard before any BSS-side write back to a
  customer.

## The trap (carried from spec §"The third trap")

Reuse on user retries → silent double-charge protection that hides
real bugs. Fresh keys on BSS restart → silent double-charge. Get the
"is this the same attempt or a new one?" check right via the
`payment_attempt` row's existence and recorded key; do not trust
caller intent.
