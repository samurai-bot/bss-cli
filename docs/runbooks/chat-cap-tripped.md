# Investigating cap-tripped customer reports

When a customer reports "I tried to chat and it told me I'd hit
the budget — I haven't been chatting that much", the question is
whether the cap accounting is correct. v0.12 ships a soft per-customer
ceiling, not a hard quota; mis-counting feels broken even if the
cap exists.

## Two caps

* **Hourly rate cap.** In-memory sliding window per customer
  (default 20 requests/hour). Resets implicitly as old timestamps
  age out of the window. Single-process — a portal restart
  resets the window for every customer.
* **Monthly cost cap.** DB-backed via `audit.chat_usage`.
  `(customer_id, period_yyyymm)` PK; cost rolled up from
  OpenRouter token counts × per-model rate. Doesn't reset on
  portal restart.

## Confirm the count is correct

```sql
-- Current month's row for this customer.
SELECT customer_id, period_yyyymm, requests_count, cost_cents,
       last_updated
FROM audit.chat_usage
WHERE customer_id = '<CUST-NNN>'
  AND period_yyyymm = (
      EXTRACT(YEAR FROM now())::int * 100
      + EXTRACT(MONTH FROM now())::int
  );
```

If `cost_cents >= BSS_CHAT_COST_CAP_PER_CUSTOMER_PER_MONTH_CENTS`
(default 200), the cap is correctly tripped. Cross-check against
the customer's interactions to estimate actual chat activity:

```sql
SELECT count(*)
FROM crm.interaction i
WHERE i.customer_id = '<CUST-NNN>'
  AND i.channel = 'portal-chat'
  AND i.created_at > now() - interval '30 days';
```

If the request count looks plausible (e.g., 150+ chats in a
month at ~1.3 cents per turn ≈ 200 cents) the cap is doing its
job — explain to the customer that the dashboard, billing, and
plan options on the site cover everything chat can do.

## Reset (operator-initiated, rare)

If a customer was misclassified (e.g., model rate table outdated,
cost over-counted), a manual reset is a UPDATE:

```sql
UPDATE audit.chat_usage
SET cost_cents = 0,
    requests_count = 0,
    last_updated = now()
WHERE customer_id = '<CUST-NNN>'
  AND period_yyyymm = <YYYYMM>;
```

Log the reset in a CRM interaction so the audit trail captures
the operator action:

```python
crm.log_interaction(
    customer_id="<CUST-NNN>",
    summary="Chat cost cap reset by operator <op-id>",
    body_text="Customer reported cap-tripped at <N> cents; counter "
              "reset because <reason>. Pre-reset state: "
              "<row dump>.",
    direction="outbound",
)
```

## Hourly window troubleshoot

The per-customer hourly window is in-memory. Two things to know:

1. **A portal restart resets the window** for every customer.
   This is intentional (single-process simplicity v1.x can
   replace with Redis if scale demands).
2. **A customer hopping IPs doesn't bypass the cap** because the
   window is keyed on `customer_id`, not IP. The per-IP cap
   exists separately for pre-login attackers.

If a customer reports the hourly cap firing immediately after a
portal restart: not possible (the window starts empty). If they
report it firing after one or two messages: check the customer's
session — they may have multiple browser tabs all hitting the
chat with rapid retries.

## What NOT to do

* **Don't disable the cap globally.** The default exists to bound
  cost; disabling it across all customers is a budget risk.
  Per-customer overrides via the table reset are the right
  granularity.
* **Don't read `os.environ` for the cap value at request time.**
  The doctrine guard catches this. Caps are loaded once at
  orchestrator startup; rotation is restart-based.
