# Phase 5 — Payment Service

## Goal

The Payment service. Mock gateway, card-on-file storage, charge attempts. Short phase — most of the pattern work was done in Phase 4. This is a clean copy of the Phase 3/4 pattern applied to a simpler domain.

## Deliverables

### Service: `services/payment/` (port **8003**)

Same structure as CRM (Phase 4): `api/`, `schemas/`, `repositories/`, `policies/`, `services/`, `events/`. The `domain/` folder contains the mock gateway.

### Endpoints (TMF676 + custom)

- `POST   /tmf-api/paymentMethodManagement/v4/paymentMethod` — register card
- `GET    /tmf-api/paymentMethodManagement/v4/paymentMethod?customerId={id}`
- `GET    /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}`
- `DELETE /tmf-api/paymentMethodManagement/v4/paymentMethod/{id}` — destructive
- `POST   /tmf-api/paymentManagement/v4/payment` — charge
- `GET    /tmf-api/paymentManagement/v4/payment/{id}`
- `GET    /tmf-api/paymentManagement/v4/payment?customerId={id}`
- `GET /health`, `GET /ready`

## Mock gateway (`app/domain/mock_gateway.py`)

```python
class MockGateway:
    async def tokenize(self, card_number: str, exp_month: int, exp_year: int) -> TokenizeResult:
        # Return tok_<uuid>, last4, brand detection from BIN
        ...

    async def charge(self, token: str, amount: Decimal, currency: str) -> ChargeResult:
        await asyncio.sleep(0.05)  # simulate latency
        if "FAIL" in token:
            return ChargeResult(status="declined", reason="card_declined_by_issuer", gateway_ref=f"mock_{uuid4()}")
        if amount <= 0:
            raise ValueError("amount must be positive")  # caught by policy layer upstream
        return ChargeResult(status="approved", gateway_ref=f"mock_{uuid4()}")
```

Brand detection from BIN ranges (simplified):
- 4 → visa
- 51–55 → mastercard
- 34, 37 → amex

## PCI note (loud comment in code)

```python
# ============================================================================
# ⚠️  THIS IS A SANDBOX. NEVER STORE PAN OR CVV IN A REAL SYSTEM.
# In production, card numbers should be sent directly from the client to a
# PCI-compliant tokenization service (Stripe, Adyen, etc). The backend
# should only ever see the resulting token. This mock tokenizes server-side
# PURELY for demo simplicity and MUST NOT be used as a pattern.
# ============================================================================
```

## Cross-service contract

Payment needs to verify customer existence when adding a card. It calls CRM via `bss-clients.CRMClient.get_customer(customer_id)`. **No shared DB access.** Same rule as all inter-service boundaries.

Create `packages/bss-clients/` in this phase:

```
packages/bss-clients/bss_clients/
├── __init__.py
├── base.py          # AsyncClient with timeouts and typed errors
├── errors.py        # ClientError, PolicyViolationFromServer, NotFound
├── crm.py           # CRMClient
├── catalog.py       # CatalogClient
└── payment.py       # PaymentClient
```

This package is now shared across services and (later) the CLI orchestrator.

## Policies required this phase

- [ ] `payment_method.add.customer_exists` — cross-service check via CRMClient
- [ ] `payment_method.add.customer_active_or_pending`
- [ ] `payment_method.add.card_not_expired`
- [ ] `payment_method.add.at_most_n_methods` — limit 5 per customer for v0.1
- [ ] `payment_method.remove.not_last_if_active_subscription` — stub (real check wired in Phase 6)
- [ ] `payment.charge.method_active`
- [ ] `payment.charge.positive_amount`
- [ ] `payment.charge.customer_matches_method`

## Events published

- `payment_method.added`, `payment_method.removed`
- `payment.charged`, `payment.declined`, `payment.errored`

## Verification checklist

- [ ] `make up` brings up payment alongside catalog and crm
- [ ] `POST /paymentMethod` with valid card returns 201, response has token, no PAN
- [ ] Logs do NOT contain card numbers (grep the container logs to prove it)
- [ ] `POST /paymentMethod` for unknown customer → 422, rule `payment_method.add.customer_exists`
- [ ] `POST /paymentMethod` with expired card → 422
- [ ] `POST /payment` with amount 10.00 SGD → approved
- [ ] `POST /payment` using a method with "FAIL" in token → declined (not error), payment_attempt row has status=declined
- [ ] `DELETE /paymentMethod/{id}` — succeeds (subscription check stubbed)
- [ ] Both approved and declined charges emit the right events and audit rows
- [ ] `make payment-test` passes
- [ ] `bss-clients.PaymentClient.charge(...)` works when called from a test

## Out of scope

- Real tokenization
- 3DS simulation
- Refunds
- Multiple currencies (SGD only)
- Partial captures
- Saved customer profiles on gateway (we do it all locally)

## Session prompt

> Read `CLAUDE.md`, `DATA_MODEL.md`, `phases/PHASE_03.md`, `phases/PHASE_04.md` (for the policy pattern), `phases/PHASE_05.md`.
>
> Confirm you will: (1) clone the Phase 3/4 skeleton, (2) create the `bss-clients` package in this phase, (3) implement the mock gateway in `domain/` not `services/`, (4) call CRM via HTTP for customer verification.
>
> Wait for approval. Implement in this order: mock_gateway → policies → services → repositories → routers → tests.

## The trap

Don't let Claude Code build a real tokenization flow. The mock is the point. If the gateway gets complicated, you're doing it wrong. Keep it to ~100 lines including the charge logic.

Also don't let Claude Code silently skip the PCI comment. That comment is documentation for any future reader and is non-negotiable.
