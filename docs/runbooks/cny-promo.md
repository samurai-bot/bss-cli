# Running a CNY-style promo

> **Audience:** operators running BSS-CLI v0.7+. Two patterns, both supported and audited; pick the one that matches the marketing narrative.

## Pattern A — windowed offering

Use when the promo is a *new* SKU (e.g. "Lunar New Year Mini Plan" with bespoke allowances). New orders during the window land on the promo SKU; the SKU disappears from the customer-facing catalog after the window.

```bash
bss admin catalog add-offering \
    --id PLAN_CNY \
    --name "Lunar New Year Mini" \
    --price 12.00 \
    --valid-from 2026-02-10T00:00:00Z \
    --valid-to 2026-02-24T00:00:00Z \
    --data-mb 30720 \
    --voice-min 200 \
    --sms-count 200
```

Customers who ordered PLAN_CNY during the window have it persisted on their subscription. They keep renewing on PLAN_CNY's snapshot price after the window closes; the offering is just no longer sellable to *new* customers.

## Pattern B — windowed price on an existing offering

Use when you want to discount an existing tier (e.g. "PLAN_M is $20 instead of $25 for two weeks") without changing what new customers are signing up *for*.

```bash
# 1. Add the promo price row alongside the existing PRICE_PLAN_M ($25 base).
bss admin catalog set-price \
    --offering PLAN_M \
    --price-id PRICE_PLAN_M_CNY \
    --amount 20.00 \
    --valid-from 2026-02-10T00:00:00Z \
    --valid-to 2026-02-24T00:00:00Z

# 2. Verify lowest-active-wins resolves PLAN_M to $20 during the window.
bss admin catalog show --at 2026-02-15T12:00:00Z
```

During the window, `get_active_price(PLAN_M)` returns $20 (lowest-active-wins). Outside the window, it returns the base $25 row. Orders placed during the window snapshot $20 on the subscription and **continue to renew at $20** for as long as the subscription is alive — that is the deliberate "promo holds for life" effect.

If the desired behaviour is "promo for two weeks then everyone on PLAN_M moves to the new price", use the migration flow instead — see `docs/runbooks/migrating-customers-to-new-price.md`.

## Verifying the result

```bash
# Inside the window — PLAN_M should price at $20.
bss admin catalog show --at 2026-02-15T12:00:00Z

# A new order during the window snapshots $20.
bss order create --customer CUST-007 --offering PLAN_M
bss subscription show SUB-NNN  # verify priceAmount = 20.00

# After the window — base $25 returns.
bss admin catalog show --at 2026-03-01T00:00:00Z
```

## Anti-pattern

Don't try to mix Pattern A and Pattern B. If you need both ("promo SKU AND a $5 off everyone"), run them as two separate, sequential operations and watch `bss admin catalog show --at <now>` to confirm only one is active at any moment. Stacked discounts are explicitly out of scope for v0.7.
