# Migrating existing customers to a new price

> **Audience:** operators running BSS-CLI v0.7+. Use when the catalog tier itself is being repriced and existing subscribers must move with it (with regulatory notice).

## Why this is its own flow

Catalog price changes via `bss admin catalog set-price` only affect *new* orders — existing subscriptions carry a price snapshot from order-creation time and renew on that snapshot forever. That is the doctrine.

When you need existing customers to move (e.g. "PLAN_M was $25, will be $30 effective May 1, with 30 days notice as required by the regulator"), use the explicit migration flow: it writes per-subscription pending fields, emits per-subscription audit events, and queues a `notification.requested` event per customer for the email layer (logging-only in v0.7).

## Procedure

```bash
# 1. Insert the new price row in catalog. Don't retire the old one yet —
#    new orders during the notice window pay the new price; existing
#    subscriptions wait for the migration to fire.
bss admin catalog set-price \
    --offering PLAN_M \
    --price-id PRICE_PLAN_M_V2 \
    --amount 30.00 \
    --currency SGD \
    --valid-from 2026-05-01T00:00:00Z \
    --retire-current

# 2. Schedule the migration with notice. effective_from + notice_days
#    (default 30) becomes pending_effective_at on each subscription.
bss admin catalog migrate-price \
    --offering PLAN_M \
    --new-price-id PRICE_PLAN_M_V2 \
    --effective-from 2026-05-01T00:00:00Z \
    --notice-days 30 \
    --initiated-by ops-${USER}
```

The CLI prints the count of affected subscriptions plus the IDs.

## What happens on the next renewal

- Each affected subscription has its `pending_offering_id = PLAN_M`,
  `pending_offering_price_id = PRICE_PLAN_M_V2`,
  `pending_effective_at = 2026-05-31T00:00:00Z` (effective_from + 30 days).
- When `subscription.renew` fires for that subscription on or after that
  moment, the renewal charges the *new* price ($30), swaps the snapshot,
  clears the pending fields, and emits `subscription.price_migrated`
  (rather than `subscription.plan_changed` — same offering, just a price
  move).
- Subscriptions that terminate during the notice window simply drop out;
  no manual cleanup needed.
- A subscription that fails its renewal payment during the migration
  stays on the old price (snapshot intact) and gets blocked per the
  existing renewal-failure policy. The pending fields are *not* cleared,
  so a manual retry (e.g. after a VAS top-up) would still apply the
  migration on the next successful charge.

## Notification

Each affected subscription gets a `notification.requested` event published
to RabbitMQ:

```json
{
  "customerId": "CUST-007",
  "channel": "email",
  "template": "price_migration_notice",
  "templateArgs": {
    "subscriptionId": "SUB-007",
    "offeringId": "PLAN_M",
    "oldAmount": "25.00",
    "newAmount": "30.00",
    "currency": "SGD",
    "effectiveAt": "2026-05-31T00:00:00+00:00"
  }
}
```

In v0.7 the only consumer is `LoggingNotificationConsumer` running in the
subscription service — it pretty-prints the payload to stdout. Real email
delivery (SMTP / SES / SendGrid) is deferred to v1.0; the regulatory
sign-off path for v0.7 is "operator pulls the events from
`audit.domain_event` and ships an external mailmerge".

## Regulatory notes (Singapore)

For upward price moves on prepaid bundles, Singapore's IMDA expects 30
days notice and a clear statement of the new price, the effective date,
and the customer's option to terminate. The `migrate-price` command's
default `notice_days=30` aligns with that minimum; the
`notification.requested` template is the place to inject the legally
required disclosure text.

## Anti-pattern

Don't bypass this flow with raw SQL — `UPDATE subscription SET
price_amount = 30 WHERE offering_id = 'PLAN_M'` skips the per-subscription
pending fields, the audit event, and the notification queue. The CLI is
the only path.
