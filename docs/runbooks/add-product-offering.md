# Adding a new product offering

> **Audience:** operators with admin access running BSS-CLI v0.7+. Adds a new tier (e.g. PLAN_XS, PLAN_XL) without a code change.

## Prerequisites

- `bss` CLI installed and pointed at the target deployment (`BSS_API_TOKEN`, service URLs in `.env`).
- A `--spec-id` value already in `catalog.product_specification`. The seeded `SPEC_MOBILE_PREPAID` covers v0.7's needs.

## Procedure

```bash
# Add PLAN_XS — 5GB data, no voice, no SMS.
bss admin catalog add-offering \
    --id PLAN_XS \
    --name "Mini" \
    --price 5.00 \
    --currency SGD \
    --data-mb 5120
```

The command writes one `product_offering` row, one `product_offering_price` row (`PRICE_PLAN_XS`), and one `bundle_allowance` row through the catalog admin service. No raw SQL.

## Verify

```bash
# Confirm the offering is now in the active catalog at the current moment.
bss admin catalog show

# Confirm a customer-facing read returns it.
bss catalog list
```

## Time-window an offering at creation

To launch a windowed offering (e.g. a CNY promotional plan that's only sellable during a date range):

```bash
bss admin catalog add-offering \
    --id PLAN_CNY \
    --name "Lunar New Year Promo" \
    --price 12.00 \
    --valid-from 2026-02-10T00:00:00Z \
    --valid-to 2026-02-24T00:00:00Z \
    --data-mb 30720
```

After 2026-02-24, `bss catalog list` no longer surfaces PLAN_CNY for new orders. Customers who ordered during the window keep their snapshot price untouched — see `docs/runbooks/migrating-customers-to-new-price.md` for explicit price moves.

## Rollback

`bss admin catalog window-offering --id PLAN_XS --valid-to <now>` retires the offering immediately for new orders. Existing subscriptions on PLAN_XS keep renewing on their snapshot price; to migrate them off, schedule a plan-change per customer or run `bss admin catalog migrate-price` for a like-for-like price move.
