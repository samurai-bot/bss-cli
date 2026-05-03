# Three-Provider Sandbox Soak (v0.16 Track 5)

> **TL;DR.** A pytest module at `scenarios/live_sandbox/` that exercises
> the BSS Stripe integration end-to-end against a real Stripe sandbox.
> Run it manually before tagging a release. Three consecutive green runs
> = release-tag confidence per spec §5.

## What this is for

Spec line 287:

> This is the test that proves "v0.14 + v0.15 + v0.16 work together."
> Without it, the three-release split is a claim, not a proof.

The soak catches drift the unit tests can't see — Stripe rate-limits,
sandbox API behavior changes, webhook signing format shifts, BSS
adapter code paths against real responses. Run it before each release
tag.

## What runs

`scenarios/live_sandbox/test_three_provider_soak.py` — five tiers:

1. **Stripe credentials valid** — `Account.retrieve` smoke; refuses to
   proceed if the key doesn't return an `acct_*`.
2. **Stripe charge round-trip** — mints a customer + off-session
   PaymentIntent with `pm_card_visa`; asserts `status='succeeded'`.
3. **BSS-side StripeTokenizerAdapter live** — exercises
   `ensure_customer` (writes `payment.customer` cache) + `charge`
   against real Stripe. Confirms the BSS adapter code path works
   against real responses, not just fixtures.
4. **Resend + Didit env-presence** — checks the env vars are SET (not
   that the APIs work). Resend keys can be scoped to send-only (correct
   production posture) which can't call read-only smoke endpoints;
   Didit's only validation API consumes against the 500/month free-tier
   cap. Real liveness for both is proven by the dedicated v0.14/v0.15
   integration tests + the operator's onboard-wizard probes (run once
   at setup).
5. **Webhook receiver round-trip** — triggers a real charge, polls for
   the resulting webhook to land in `integrations.webhook_event`
   within 60 seconds. Requires `BSS_PAYMENT_WEBHOOK_PUBLIC_URL` to be
   set to a publicly-reachable URL serving this BSS instance's
   `/webhooks/stripe` (Tailscale Funnel, ngrok, prod URL, etc.); skips
   cleanly if unset.

The portal Stripe Elements iframe is **NOT** exercised here — full
browser E2E needs Playwright/Selenium which is its own infrastructure
project (post-v0.16). The unit-tested rendering in
`portals/self-serve/tests/test_signup_stripe_mode.py` is the closest
we get without a browser harness. **Manual full E2E is the operator's
responsibility before each release tag** (see "Manual smoke before
release" below).

## Running the soak

Required env (already in your `.env` if you've completed `bss onboard`
for payment + email + KYC):

```
BSS_PAYMENT_STRIPE_API_KEY=sk_test_...
BSS_PAYMENT_STRIPE_PUBLISHABLE_KEY=pk_test_...
BSS_PAYMENT_STRIPE_WEBHOOK_SECRET=whsec_...
BSS_PORTAL_KYC_DIDIT_API_KEY=...
BSS_PORTAL_KYC_DIDIT_WORKFLOW_ID=...
BSS_PORTAL_EMAIL_RESEND_API_KEY=re_...
BSS_DB_URL=postgresql+asyncpg://...
```

Optional (enables Tier 5 — webhook round-trip):

```
BSS_PAYMENT_WEBHOOK_PUBLIC_URL=https://<your-funnel-host>/webhooks/stripe
```

Then run three consecutive times:

```bash
set -a && source .env && set +a
for i in 1 2 3; do
  echo "=== run $i/3 ==="
  BSS_NIGHTLY_SANDBOX=true \
    PYTHONPATH=services/payment:scenarios \
    uv run --package payment pytest scenarios/live_sandbox/ -q
done
```

Three green runs = release-gate cleared per spec §5.

Each run takes ~8.5 seconds wall-clock. Per-run cost:
- Stripe: ~6 sandbox API calls (Account.retrieve + Customer.create × 3
  + PaymentIntent.create × 3) — $0, well under Stripe's 100 req/sec
  test-mode allowance
- Resend: 0 calls (env-presence check only; real send happens only
  during the manual UI smoke)
- Didit: 0 calls (env-presence check only; the 500/month cap is
  untouched)

## Sanity guards

The soak refuses to run if anything looks wrong:

- `BSS_NIGHTLY_SANDBOX!=true` → entire module skipped (zero external
  calls). A normal `make test` makes ZERO Stripe calls; only this
  explicit invocation does.
- Any required Stripe secret unset with `BSS_NIGHTLY_SANDBOX=true` →
  `pytest.fail` with the specific missing var name.
- `BSS_PAYMENT_STRIPE_API_KEY` starts with `sk_live_` →
  `pytest.fail("BSS_NIGHTLY_SANDBOX must NEVER run against live keys")`.
  Non-negotiable safety belt; the soak charges real test cards but
  they must be test-mode cards.

## Reading the output

```
.......                                                                  [100%]
7 passed in 8.5s
```

All green. Re-run twice more; if all three runs are green, release-gate
cleared.

```
.....F.                                                                  [100%]
1 failed, 6 passed in 8.5s
FAILED ::TestStripeChargeRoundTrip::test_off_session_charge_with_test_card
  pi.status = 'requires_action' (3DS challenge)
```

A flake → **investigate before tagging the release.** Spec line 285:
"do not paper over." The most common real causes:

- **Stripe regulatory enforcement** — sandbox sometimes mimics live
  3DS / SCA requirements for testing. `pm_card_visa` shouldn't trigger
  this; if it does, swap to a different test PM and document why.
- **Sandbox rate limits** — Stripe sandbox occasionally rate-limits
  identical idempotency keys; the soak generates fresh UUIDs per run
  so this shouldn't happen, but if you see consecutive 429s, raise it
  with Stripe support.
- **Webhook delivery delay** — Tier 5's 60s budget is generous; if
  the webhook never arrives, check Stripe Dashboard → Developers →
  Webhooks → endpoint → Recent deliveries for explicit failures and
  the BSS payment service logs for `payment.webhook.signature_invalid`
  diagnostics.

## Manual smoke before release

The Track 5 automated soak doesn't drive the portal Stripe Elements
iframe (browser-driven; needs Playwright). Before tagging v0.16 the
operator should run a manual full-stack signup with:

```
BSS_PAYMENT_PROVIDER=stripe
BSS_PORTAL_KYC_PROVIDER=didit
BSS_PORTAL_EMAIL_PROVIDER=resend
BSS_ENV=development  (or staging in your sandbox)
```

End-to-end checklist:

1. ☐ Open `/welcome` (or your Tailscale Funnel URL) in a real browser
2. ☐ Sign up with a fresh email; click magic link in the dev mailbox
   (or Resend inbox if running staging)
3. ☐ Pick a plan; verify form does NOT show the mock card-number input
4. ☐ Complete Didit KYC in the hosted UI
5. ☐ At the COF step, verify the Stripe Elements iframe loads
6. ☐ Enter `4242 4242 4242 4242`; click "Save card & continue"
7. ☐ Verify the signup chain advances through `pending_order` →
   `pending_activation` → `completed`
8. ☐ Stripe dashboard → Customers shows a new `cus_*` with the BSS
   customer id in metadata
9. ☐ Stripe dashboard → Payments shows the charge
10. ☐ Resend dashboard shows the welcome / receipt emails
11. ☐ `stripe trigger charge.dispute.created` → BSS structlog shows
    `payment.webhook.received outcome=reconciled domain_event=payment.dispute_opened`
12. ☐ Stripe dashboard → refund the test charge → BSS structlog shows
    `payment.webhook.received outcome=reconciled domain_event=payment.refunded`

Three consecutive successful manual runs = release-tag confidence.

## Why this isn't more automated

A full UI E2E test (browser-driven Stripe Elements + portal Didit
hosted UI handoff + email click) would need:

- A headless browser (Playwright)
- A way to read the Resend inbox or Tailscale-tunneled email-test box
- A way to drive the Didit hosted UI's mocked sandbox flow
- ~30s of wall time per run × 3 runs = >1.5 min per cycle

That's its own project, scoped post-v0.16. The Track 5 soak is the
"the integration code paths work against real providers" smoke; the
operator's manual checklist above is the "the customer-facing flow
hangs together" gate.

If a future contributor wants to ship the Playwright soak, the right
shape is `scenarios/live_sandbox_browser/` as a sibling to this
module, with its own pytest fixture for the browser, gated on a
separate `BSS_NIGHTLY_SANDBOX_BROWSER=true` so the cheaper headless
soak can still run without it.
