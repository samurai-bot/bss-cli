# Adding a new product offering

> **Audience:** operators with admin access running BSS-CLI v0.7+. Adds a new tier (e.g. PLAN_XS, PLAN_XL, PLAN_M_ROAM) without a code change.
>
> **See also:** [`docs/HANDBOOK.md` §8.1](../HANDBOOK.md#81-catalog--add-an-offering-with-roaming) for the full catalog runbook in context. [`docs/runbooks/cny-promo.md`](cny-promo.md) for windowed-offering promo patterns. [`docs/runbooks/migrating-customers-to-new-price.md`](migrating-customers-to-new-price.md) for moving existing subscribers.

## Prerequisites

- `bss` CLI installed and pointed at the target deployment (`BSS_API_TOKEN`, service URLs in `.env`).
- A `--spec-id` value already in `catalog.product_specification`. The seeded `SPEC_MOBILE_PREPAID` covers v0.7+ needs.

## Procedure (data + voice + SMS)

```bash
# Add PLAN_XS — 5GB data, no voice, no SMS, no roaming.
bss admin catalog add-offering \
    --id PLAN_XS \
    --name "Mini" \
    --price 5.00 \
    --currency SGD \
    --data-mb 5120
```

The command writes one `product_offering` row, one `product_offering_price` row (`PRICE_PLAN_XS`), and one `bundle_allowance` row (data) through the catalog admin service. No raw SQL.

Optional flags:
- `--voice-min N` — adds a `voice` allowance (`-1` for unlimited).
- `--sms-count N` — adds an `sms` allowance (`-1` for unlimited).
- `--valid-from <iso>` / `--valid-to <iso>` — windows the offering at creation (see [Time-window an offering](#time-window-an-offering-at-creation) below).

## Verify

```bash
bss admin catalog show          # Active catalog at the current moment
bss catalog list                # Customer-facing read
```

## Roaming (v0.17+)

> [!warning] **CLI gap (acknowledged).** `bss admin catalog add-offering` does **not** yet expose a `--data-roaming-mb` flag. Server-side support exists (the catalog service writes `data_roaming` rows from seed; subscription materializes balances on top-up; rating routes by `roaming_indicator`), but the admin HTTP endpoint and CLI haven't been extended. This will be fixed in a future minor release.

Roaming is a first-class allowance type alongside `data`, `voice`, `sms`. Two facts about roaming worth knowing before adding an offering:

1. **Roaming is additive.** A subscription's `is_exhausted` predicate considers only the *primary* allowance set (`data`, `voice`, `sms`). An exhausted `data_roaming` balance rejects roaming usage with rule `subscription.usage_rated.roaming_balance_required` but the subscription itself stays `active` (home data still works).
2. **A plan with zero included roaming can still accept a roaming top-up.** When the customer purchases `VAS_ROAMING_1GB`, the subscription synthesizes a fresh `data_roaming` `BundleBalance` row.

### Path A — Add the offering, then attach a `data_roaming` allowance via SQL

```bash
# 1. Create the offering with primary allowances.
bss admin catalog add-offering \
    --id PLAN_XS_ROAM \
    --name "Mini + Roaming" \
    --price 8.00 \
    --currency SGD \
    --data-mb 5120

# 2. Attach the roaming allowance directly via SQL.
psql "$BSS_DB_URL" <<'SQL'
INSERT INTO catalog.bundle_allowance (id, offering_id, allowance_type, quantity, unit)
VALUES ('BA_PLAN_XS_ROAM_ROAM', 'PLAN_XS_ROAM', 'data_roaming', 1024, 'mb');
SQL

# 3. Verify — the offering now lists 4 allowance lines: data, data_roaming, voice if any, sms if any.
bss admin catalog show
```

The id pattern `BA_<OFFERING_ID>_ROAM` mirrors the seed convention (`BA_M_ROAM`, `BA_L_ROAM`).

### Path B — Extend the seed module and re-seed (recommended for permanent additions)

Edit `packages/bss-seed/bss_seed/catalog.py`. The `allowances` list (~line 62) carries the seeded plans + their `data_roaming` rows in a stable 4-row pattern:

```python
allowances = [
    # PLAN_XS_ROAM — 5GB data, 1GB roaming, no voice/SMS.
    ("BA_XS_ROAM_DATA", "PLAN_XS_ROAM", "data", 5120, "mb"),
    ("BA_XS_ROAM_ROAM", "PLAN_XS_ROAM", "data_roaming", 1024, "mb"),
    # ... existing seeded plans below ...
]
```

`make seed` is idempotent (`ON CONFLICT DO NOTHING`); rows already in DB are untouched, new rows land. Recommended for permanent additions because the seed is the documented source of truth and reads sensibly in code review.

### Customers without included roaming can still top up

A customer on `PLAN_S` (which carries `data_roaming = 0 mb`) can still purchase `VAS_ROAMING_1GB`. The subscription's `purchase_vas` materializes a `data_roaming` `BundleBalance` row on demand. After exhaustion, roaming usage is rejected with `subscription.usage_rated.roaming_balance_required` while home data keeps working — see [`docs/HANDBOOK.md` §7.6](../HANDBOOK.md#76-roaming-v017).

## Time-window an offering at creation

To launch a windowed offering (e.g. a CNY promotional plan that's only sellable during a date range):

```bash
bss admin catalog add-offering \
    --id PLAN_CNY \
    --name "Lunar New Year Promo" \
    --price 12.00 \
    --currency SGD \
    --valid-from 2026-02-10T00:00:00Z \
    --valid-to 2026-02-24T00:00:00Z \
    --data-mb 30720
```

After 2026-02-24, `bss catalog list` no longer surfaces `PLAN_CNY` for new orders. Customers who ordered during the window keep their snapshot price untouched — see [`docs/runbooks/migrating-customers-to-new-price.md`](migrating-customers-to-new-price.md) for explicit price moves.

## Verify with point-in-time queries

```bash
# What was sellable on 2026-02-15?
bss admin catalog show --at 2026-02-15T00:00:00Z

# Active right now (default).
bss admin catalog show
```

## Rollback

```bash
bss admin catalog window-offering --id PLAN_XS --valid-to <now>
```

Retires the offering immediately for new orders. Existing subscriptions on PLAN_XS keep renewing on their snapshot price. To migrate them off:
- Schedule a plan-change per customer via `subscription.schedule_plan_change`, OR
- Run `bss admin catalog migrate-price --offering PLAN_XS --new-price-id <PRICE-XX>` for a like-for-like price move (see [`migrating-customers-to-new-price.md`](migrating-customers-to-new-price.md)).
