# Three-Provider Sandbox Soak (v0.16 Track 5)

> **TL;DR.** Nightly CI workflow at `.github/workflows/nightly-sandbox.yml`
> runs the live-sandbox soak test 3 consecutive times against
> Stripe + Resend + Didit sandbox accounts. Three green = v0.16 release
> gate cleared per spec §5. The soak is gated on `BSS_NIGHTLY_SANDBOX=true`
> + repo secrets so a normal `make test` never touches external APIs.

## Why this exists

Spec line 287:

> This is the test that proves "v0.14 + v0.15 + v0.16 work together."
> Without it, the three-release split is a claim, not a proof.

Real-provider integrations have failure modes that mocks don't model:
- Stripe rate-limits during peak signup windows
- Didit's 500-session monthly cap exhaustion
- Resend bounces racing renewal-receipt sends
- Stripe webhook delivery delays that confuse renewal-time idempotency

The soak catches drift in all three before it hits a customer.

## What runs

`scenarios/live_sandbox/test_three_provider_soak.py` — five tiers:

1. **Stripe credentials valid** — `Account.retrieve` smoke; refuses to
   proceed if it doesn't return an `acct_*`.
2. **Stripe charge round-trip** — mints a customer + off-session
   PaymentIntent with `pm_card_visa`; asserts `status='succeeded'`.
3. **BSS-side StripeTokenizerAdapter live** — exercises
   `ensure_customer` (writes `payment.customer` cache) + `charge`
   against real Stripe. Confirms BSS's adapter code path works end-to-end.
4. **Resend + Didit credential smoke** — single API ping each.
   Confirms the keys are alive without exercising the full email/KYC
   flow (those have their own dedicated v0.14/v0.15 hero scenarios).
5. **Webhook receiver round-trip** (optional, gated on
   `BSS_PAYMENT_WEBHOOK_PUBLIC_URL`) — triggers a real charge, polls
   for the resulting webhook to land in `integrations.webhook_event`
   within 60 seconds.

The portal Stripe Elements iframe is **NOT** exercised here — full
browser E2E needs Playwright/Selenium which is its own infrastructure
project (post-v0.16). The unit-tested rendering in
`portals/self-serve/tests/test_signup_stripe_mode.py` is the closest
we get without a browser harness. **Manual full E2E is the operator's
responsibility before each release tag** (see "Manual smoke before
release" below).

## Repo secrets to configure

GitHub → Settings → Secrets and variables → Actions → New repository
secret. Required:

| Secret | Format | Source |
|---|---|---|
| `BSS_PAYMENT_STRIPE_API_KEY` | `sk_test_...` | Stripe Dashboard → Developers → API keys |
| `BSS_PAYMENT_STRIPE_PUBLISHABLE_KEY` | `pk_test_...` | Same dashboard page |
| `BSS_PAYMENT_STRIPE_WEBHOOK_SECRET` | `whsec_...` | Stripe Dashboard → Developers → Webhooks → endpoint → Signing secret |
| `BSS_PORTAL_KYC_DIDIT_API_KEY` | varies | Didit dashboard, sandbox tier |
| `BSS_PORTAL_KYC_DIDIT_WORKFLOW_ID` | UUID | Didit dashboard → Workflows |
| `BSS_PORTAL_EMAIL_RESEND_API_KEY` | `re_...` | Resend dashboard → API keys |

Optional (enables Tier 5 webhook round-trip):

| Secret | Notes |
|---|---|
| `BSS_PAYMENT_WEBHOOK_PUBLIC_URL` | A publicly-reachable URL serving this BSS instance's `/webhooks/stripe` (Tailscale Funnel, ngrok, prod URL, etc.). Test skips cleanly if unset. |

## Sanity guards

The soak refuses to run if anything looks wrong:

- `BSS_NIGHTLY_SANDBOX!=true` → entire module skipped (zero external
  calls).
- Any required secret unset → `pytest.fail` with the specific missing
  var name; no partial run.
- `BSS_PAYMENT_STRIPE_API_KEY` starts with `sk_live_` →
  `pytest.fail("BSS_NIGHTLY_SANDBOX must NEVER run against live keys")`.
  This is a non-negotiable safety belt; the soak charges real test
  cards, but they must be test-mode cards.

## Reading the workflow output

```
✅ run 1/3: green        ✅ release gate cleared
✅ run 2/3: green
✅ run 3/3: green
```

Three runs all green → v0.16 release gate cleared for the day.

```
✅ run 1/3: green
❌ run 2/3: TestStripeChargeRoundTrip::test_off_session_charge_with_test_card
   pi.status = 'requires_action' (3DS challenge)
✅ run 3/3: green
```

A flake → **investigate before tagging the release**. Spec line 285:
"do not paper over." The most common real causes:

- **Stripe regulatory enforcement** — sandbox sometimes mimics live
  3DS / SCA / regulatory requirements for testing. `pm_card_visa`
  shouldn't trigger this; if it does, swap to a different test PM and
  document why.
- **Provider sandbox rate limits** — Stripe sandbox occasionally
  rate-limits identical idempotency keys; the soak generates fresh
  UUIDs per run so this shouldn't happen, but if you see consecutive
  429s, raise it with Stripe support.
- **Webhook delivery delay** — Tier 5's 60s budget is generous; if
  the webhook never arrives, check Stripe Dashboard → Developers →
  Webhooks → endpoint → Recent deliveries for explicit failures and
  the BSS payment service logs for `payment.webhook.signature_invalid`
  diagnostics.

## Running locally

You can run the soak by hand against your sandbox creds:

```bash
set -a && source .env && set +a
BSS_NIGHTLY_SANDBOX=true \
  PYTHONPATH=services/payment:scenarios \
  uv run --package payment pytest scenarios/live_sandbox/ -v
```

Without `BSS_NIGHTLY_SANDBOX=true` the entire module skips with the
message "skipping live-sandbox soak".

## Manual smoke before release

The Track 5 automated soak doesn't drive the portal Stripe Elements
iframe (browser-driven; needs Playwright). Before tagging v0.16 the
operator should run a manual full-stack signup with:

```
BSS_PAYMENT_PROVIDER=stripe
BSS_PORTAL_KYC_PROVIDER=didit
BSS_PORTAL_EMAIL_PROVIDER=resend
BSS_ENV=staging  (or development in your sandbox)
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

## Cost

The soak makes the following live-API calls per run:

| Provider | Calls | Cost |
|---|---|---|
| Stripe | ~6 (Account.retrieve + Customer × 3 + PaymentIntent × 3) | $0 (test mode) |
| Resend | 1 (ApiKeys.list) | $0 (read-only) |
| Didit | 1 (Workflows.get) | $0 (read-only); does NOT consume a session against the 500/month cap |

Three runs per night × 30 nights = ~540 Stripe API calls, well under
Stripe's 100 req/sec test-mode allowance. Didit cap is untouched; the
session-consuming flow stays in the dedicated v0.15 manual scenarios.

## Why this isn't more comprehensive

A full UI E2E test (browser-driven Stripe Elements + portal Didit
hosted UI handoff + email click) would need:

- A headless browser (Playwright)
- A way to read the Resend inbox or Tailscale-tunneled email-test box
- A way to drive the Didit hosted UI's mocked sandbox flow
- ~30s of wall time per run × 3 runs = >1.5 min CI per night

That's its own project, scoped post-v0.16. The Track 5 soak is the
"the integration code paths work against real providers" smoke; the
operator's manual checklist above is the "the customer-facing flow
hangs together" gate.

If a future contributor wants to ship the Playwright soak, the right
shape is `scenarios/live_sandbox_browser/` as a sibling to this
module, with its own pytest fixture for the browser, gated on a
separate `BSS_NIGHTLY_SANDBOX_BROWSER=true` so the cheaper headless
soak can still run nightly even when the browser one is broken.
