# Stripe Cutover Playbook (v0.16+)

> **TL;DR.** When you flip `BSS_PAYMENT_PROVIDER=mock → stripe`, every
> existing `payment_method.token` in the DB is unusable (mock format,
> not a Stripe `pm_*`). Two paths handle this:
>
> 1. **Lazy-fail (default).** Next charge against any saved card fails
>    cleanly with `payment.charge.token_provider_matches_active`; the
>    customer sees "your saved payment method is no longer valid" and
>    re-adds via the portal's Stripe Elements flow.
> 2. **Proactive (`bss payment cutover --invalidate-mock-tokens`).**
>    Marks every saved card as expired BEFORE the cutover; emits an
>    event per row so the email-template flow can notify each customer
>    "please update your payment method".
>
> **Run the proactive path before flipping the env var in production.**
> Lazy-fail is honest with bundled-prepaid posture (failed charge =
> block) but creates a wave of failed renewals at the natural renewal
> boundary. Proactive smooths the cutover over a notification window.

## When this matters

A `payment.payment_method.token` row minted under
`BSS_PAYMENT_PROVIDER=mock` has the form `tok_<uuid>`. Stripe's
`PaymentIntent.create` requires a `pm_*` id from a real Elements
flow. Mixing them is fatal.

The `payment.payment_method.token_provider` column distinguishes:

```
'mock'    — tok_<uuid>, dev/sandbox only, unusable in stripe-mode
'stripe'  — pm_*, real, usable in stripe-mode
```

`PaymentService.charge` checks this on every charge via the
`payment.charge.token_provider_matches_active` policy. Mismatch raises
with a structured rule pointing to this runbook.

## The proactive path

### 1. Preview (dry-run)

```bash
BSS_PAYMENT_PROVIDER=mock bss payment cutover --invalidate-mock-tokens --dry-run
```

Output:

```
Found 47 active payment_methods with token_provider='mock'.
Dry run — no writes performed.
  would invalidate: PM-0001
  would invalidate: PM-0002
  ...
```

This is read-only. Use it to validate the scope before running for
real.

### 2. Invalidate

```bash
BSS_PAYMENT_PROVIDER=mock bss payment cutover --invalidate-mock-tokens
```

Output:

```
Found 47 active payment_methods with token_provider='mock'.
Mark all as expired? Customers will see 'please update your payment
method' on next attempt. [y/N] y
Invalidated 47 payment methods.
Each row emitted a payment_method.cutover_invalidated event for the
email-template flow to pick up.
```

This sets `status='expired'` on every active mock-token row and emits
a `payment_method.cutover_invalidated` domain event per row. The
event payload carries `customer_id`, `last4`, `brand`, and `reason='operator_cutover'`.

### 3. Wait for the email window

The v0.14 Resend email-template flow consumes the
`payment_method.cutover_invalidated` event and dispatches a
"please update your payment method" email per customer. Default
template lives in the portal-side template store; customize per
operator branding before running cutover.

Recommended notification window: 7 days. Customers who add a new card
via the portal during this window are seamless; customers who don't,
fail their next renewal cleanly (lazy-fail path).

### 4. Flip the env var

Once notifications have gone out, switch `BSS_PAYMENT_PROVIDER=stripe`
in the operator's `.env` and restart the payment service:

```bash
sed -i 's|^BSS_PAYMENT_PROVIDER=.*|BSS_PAYMENT_PROVIDER=stripe|' .env
docker compose restart payment
```

Service refuses to start if any of the four startup guards trips —
see `select_tokenizer.py` for the full list (sk_test_* in production,
missing webhook secret, etc.). If the service is up, the cutover is
live; new charges go to Stripe.

## The lazy-fail path

If you skip the proactive path (or you're cutting over a small dev
deployment where 47 customer emails would be over-engineered), the
contract is:

- Every saved card stays `status='active'` with `token_provider='mock'`.
- `BSS_PAYMENT_PROVIDER=stripe` is flipped without warning.
- The next charge against any saved card raises
  `PolicyViolation(rule="payment.charge.token_provider_matches_active")`.
- The portal's "card no longer valid" template fires; customer adds a
  new card via Stripe Elements; charge retries.

This is honest with the bundled-prepaid posture (failed charge =
block, no grace period). It's the right path for sandbox, demo, and
small dev deployments.

It is the wrong path for any production deployment where you'd prefer
NOT to surprise 47 customers at their next renewal boundary
simultaneously.

## Customer-comms checklist

Before running `bss payment cutover --invalidate-mock-tokens`:

- [ ] Confirm the `payment_method.cutover_invalidated` consumer is
      wired (Resend template configured, send-rate within Resend's
      plan).
- [ ] Decide notification window (default: 7 days).
- [ ] Confirm the portal Stripe Elements flow (Track 2) is
      production-ready: `BSS_PAYMENT_PROVIDER=stripe`,
      `BSS_ENV=production`, `pk_live_*` configured, PCI-scope template
      scan passes at boot, end-to-end "add a card" verified manually.
- [ ] Plan a fallback in case Stripe is misconfigured at cutover time
      — keep `BSS_PAYMENT_PROVIDER=mock` ready to roll back, expired
      rows can be re-activated by the operator (simple `UPDATE` SQL).

## What can go wrong

- **Cutover before Stripe Elements is wired (Track 2)**, customers
  get a "card no longer valid" email but the portal's add-COF page
  still renders the v0.1 mock card-number form. They add a card,
  it's tokenized as `tok_<uuid>` again, the next charge fails. **Don't
  cut over until Track 2 ships.**
- **Cutover with the wrong `whsec_*` configured**, charges work but
  webhooks 401. The receiver's diagnostic logging
  (`payment.webhook.signature_invalid`) makes this obvious in
  structlog within minutes. Rotate the secret or fix the env var,
  then `stripe events resend` from the dashboard for any missed
  deliveries.
- **Cutover mid-renewal-batch**, half the renewal charges go to mock
  (succeed silently) and half go to Stripe (fail because the saved
  cards are pre-cutover). **Cut over OUTSIDE renewal windows.** Use
  `bss-clock` to verify no renewal jobs are scheduled in the next
  hour before flipping.

## The trap (carried from spec §"The fifth trap")

A `payment_method.token` minted as a mock token is unusable when
Stripe is selected. The first real-world cutover will not be the
first time anyone thinks about this — that's why this runbook exists.
Test the lazy-fail path. Test the proactive cutover CLI. Document the
customer-comms sequence. The cost of a bad cutover is "every
customer's next charge fails simultaneously"; the cost of a good
cutover is "47 customers re-add their card over a week."
