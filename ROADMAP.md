# BSS-CLI Roadmap

> Honest about where things stand. *Shipped* is committed and tagged. *Near-term* has a Phase or version spec drafted. *Future* is speculative — listed because they've come up enough to deserve a note, not because they're committed. *Non-goals* are things the project deliberately doesn't do, restated from `CLAUDE.md` so a stranger can find them.

## Shipped

| Tag | Date | What it added |
|---|---|---|
| **v0.1.0** | 2026-04-13 | First shippable demo. 9 services + CLI + LLM orchestrator. Hero scenarios: customer signup → exhaust, fault-injected provisioning retry, LLM-driven blocked-subscription troubleshoot. ~75 LLM tools registered. |
| **v0.1.1** | 2026-04-13 | Drift cleanup. Billing service formally deferred to v0.2 (port 8009 reserved); CLAUDE.md reconciled (LiteLLM → OpenRouter, 10 → 9 containers). |
| **v0.2.0** | 2026-04-23 | OpenTelemetry across every service. `bss trace for-order/for-subscription/get` ASCII swimlane in the terminal. Jaeger BYOI + bundled paths. Fourth hero scenario asserts span fan-out. |
| **v0.3.0** | 2026-04-23 | Shared `BSS_API_TOKEN` middleware on every BSS service. CLI + orchestrator + scenario runner inject the header automatically. Sentinel `changeme` rejects on startup. Token rotation runbook. |
| **v0.4.0** | 2026-04-23 | Self-serve customer portal on port **9001**. FastAPI + Jinja + HTMX. **Every portal write goes through the LLM orchestrator** — not bss-clients. Agent log widget streams tool calls live via SSE. Pre-baked Myinfo KYC, mock tokenizer, eSIM QR PNG. Fifth hero scenario drives the portal HTTP-to-end. |
| **v0.5.0** | 2026-04-23 | CSR agent console on port **9002**. Stub login (NOT real auth — populates `X-BSS-Actor` for audit). Search by name or MSISDN, customer 360, ask form. Agent receives customer + subscription snapshot in the prompt. Auto-refresh on completion. Shared `bss-portal-ui` package extracted before second portal was written. Sixth hero scenario. |
| **v0.6.0** | 2026-04-23 | Maintenance + polish. Docs sweep (README, ARCHITECTURE, CONTRIBUTING, ROADMAP, screenshots). Renderer polish on 5 hero ASCII renderers. Tech-debt sweep (catalog reorg, Dockerfile evaluation, doctrine grep guard, TOOL_SURFACE reconciliation, ship-criteria re-measurement). |
| **v0.7.0** | 2026-04-26 | Catalog versioning + plan changes. Subscription price snapshotted at order time; renewal reads the snapshot, not the catalog. `subscription.schedule_plan_change` + `cancel_pending_plan_change` + `migrate_to_new_price`. New hero scenario. |
| **v0.8.0** | 2026-04-26 | Self-serve portal authentication. Email + magic-link / OTP via `bss-portal-auth`. Server-side sessions, public-route allowlist, step-up auth scaffolding. |
| **v0.9.0** | 2026-04-27 | Named tokens at the BSS perimeter. `TokenMap` + `service_identity` propagation through audit + structlog + OTel. `astream_once(service_identity=)`. |
| **v0.10.0** | 2026-04-27 | Authenticated post-login customer self-serve writes go direct via `bss-clients` (chat stays orchestrator-mediated). Per-resource ownership policies + step-up gating. |
| **v0.11.0** | 2026-04-27 | Signup funnel goes direct (sub-second per step vs ~85s via the orchestrator). Chat is the only orchestrator-mediated route post-v0.11. |
| **v0.12.0** | 2026-04-30 | Chat surface + scoping. `customer_self_serve` tool profile + `*.mine` wrappers + ownership trip-wire + per-customer caps + 5-category escalation. 14-day soak. |
| **v0.12.1** | 2026-04-30 | Step-up replay preserves POST body so changes apply on first try. |
| **v0.13.0** | 2026-05-01 | Operator cockpit. CLI REPL canonical, browser veneer over a shared Postgres-backed `Conversation` store (`bss-cockpit` package). v0.5 staff-auth pattern retired. `OPERATOR.md` + `settings.toml` for operator-tunable persona + machine config. `operator_cockpit` tool profile + `BSS_OPERATOR_COCKPIT_API_TOKEN`. New hero scenario `operator_cockpit_handle_blocked_subscription`. |
| **v0.14.0** | 2026-05-02 | Real-provider integration arc begins. Per-domain adapter Protocols (`EmailAdapter` first; KYC + payment + eSIM follow). New `integrations` schema for forensic external-call + webhook-event logging. `ResendEmailAdapter` for transactional auth mail. `bss-webhooks` package with signature verification + redaction. Doctrine: no unified `Provider.execute()` API; webhook receivers carve out of `BSSApiTokenMiddleware` (provider-signature auth instead). |
| **v0.15.0** | 2026-05-02 | KYC (Didit) + eSIM-provider seam. `KycAdapter` Protocol with `prebaked` and `didit` impls. `services/kyc/` deliberately NOT a separate service — KYC verification stays channel-layer; BSS only verifies signed attestations. `kyc_webhook_corroboration` table is the trust anchor (raw Didit JSON is forgeable; signed webhook is not). PII reduction on the BSS boundary: `document_number_last4` + `document_number_hash` only. `EsimProvisioner` Protocol stub for later real-provider work. |
| **v0.16.0** | 2026-05-03 | Payment (Stripe Checkout + webhook reconciliation). Track 0 sandbox-probe-first doctrine inherited from v0.15 retrospective. `TokenizerAdapter` Protocol with `mock` + `stripe` impls. Portal does Stripe-hosted Checkout (full-page redirect) — PAN never touches BSS in production. PCI scope guard refuses to boot the portal in production-stripe mode if a card-number `<input>` field survives in any rendered template. `payment.customer` table caches per-(BSS customer, provider) Stripe `cus_*` ref. Webhook is *secondary* source of truth (sync charge response is primary; webhook reconciles + detects drift via `payment.attempt_state_drift` event). Chargebacks + out-of-band refunds are record-only — motto #1. v0.16 idempotency uses `r0` only; crash-restart retry path documented but not implemented. |
| **v0.17.0** | 2026-05-03 | Telco hygiene release. Three real-telco gaps closed: MNP (`crm.port_request` aggregate with FSM `requested → validated → completed | rejected`, operator-driven via REPL `/ports` + cockpit `port_request.*` tools), MSISDN replenishment (`bss inventory msisdn add-range` + `inventory.msisdn.pool_low` low-watermark event), and roaming as a product (new `data_roaming` allowance type — additive bucket; `VAS_ROAMING_1GB` top-up). `UsageEvent.roaming_indicator: bool` routes the rating decrement to the roaming balance; subscription-level block-on-exhaust independence (roaming exhaustion blocks roaming usage but not the subscription). Four new hero scenarios. Single Alembic migration (`0019`); no new doctrine pillars, no new auth model, no new external integrations. |
| **v0.18.0** | 2026-05-04 | Automated subscription-renewal worker. In-process tick loop in the subscription service's lifespan polls `subscription.subscription` for due rows and dispatches the existing `renew()` (no logic duplication). New `last_renewal_attempted_at` column + `FOR UPDATE SKIP LOCKED` make the loop multi-replica safe by construction. New `subscription.renewal_skipped` audit event for blocked-overdue subs (cockpit dashboard signal). Admin endpoint `POST /admin-api/v1/renewal/tick-now` (gated by `BSS_ALLOW_ADMIN_RESET`) drives one deterministic sweep for scenarios. Worker can be disabled via `BSS_RENEWAL_TICK_SECONDS=0`. One new hero scenario asserts the worker fires on its own + idempotency holds across consecutive ticks. Single Alembic migration (`0020`); no new container, no new auth, no new external integration. |

## Toward v1.0 — what's left to swap

v0.16 shipped real Stripe (Checkout + webhook reconciliation).
v0.15 shipped real Didit KYC (with prebaked dev-path preserved).
v1.0 is what's left to make the platform production-real:

- **Real Singpass / channel-layer eKYC for SG market.** Didit
  covers most jurisdictions; a Singapore-market deploy would
  swap the channel-layer adapter for a Singpass-issued signed
  JWT. BSS-CLI's contract (`customer.attest_kyc` accepts a signed
  attestation, records the corroboration_id, enforces
  `order.create.requires_verified_customer`) does not change.
- **Real SM-DP+ integration for eSIM provisioning.** The
  v0.15 `EsimProvisioner` Protocol stub gets a real GSMA SGP.22
  adapter. The `inventory.esim` pool, the
  `subscription.get_esim_activation` LPA bundle, and the activation
  state machine are all unchanged shape. The `ESIM_PROFILE_REARM`
  SOM task ships then.
- **Public soak.** Real-customer-cohort exposure with all three
  real integrations live, monitored against the v0.12 soak gates
  (zero ownership trips, p99 chat latency, no DB unbounded growth)
  re-run on production data shapes.

v1.0 is **not** a new feature ladder; nothing in v0.7–v0.18 is
renegotiated. The data model, tool surface, doctrine, and audit
trail are stable. Tagging v1.0 without the SM-DP+ swap (the only
remaining mock in the production-shape stack) is a doctrine break.

## Phase 12 — Authentication & RBAC (staff-side retired in v0.13; customer-side concrete)

The original Phase 12 plan covered both staff and customer auth.
v0.13 split the question:

- **Staff side (operator cockpit) — RETIRED.** v0.13 deletes the
  v0.5 stub-login pattern and explicitly retires the OAuth/RBAC
  ambition for the cockpit. The cockpit runs single-operator-by-
  design behind a secure perimeter; `actor` from `.bss-cli/settings.toml`.
  Multi-operator separation, if ever needed, is a multi-tenant
  carve-out (one cockpit container per operator namespace), not a
  login wall. DECISIONS 2026-05-01 documents the rationale.
- **Customer side (self-serve portal) — concrete and partially
  shipped.** v0.8 ships email + magic-link / OTP. v0.10 adds
  step-up. v1.0 swaps email-OTP for real Singpass attestation
  through the channel layer. No `services/auth`, no OAuth client
  credentials JWT for service-to-service in v0.13's plan — the
  v0.9 named-token model is the durable shape there.

`auth_context.py` stays in every service. It carries `actor` /
`tenant_id` / `service_identity`. The seam is preserved against a
future need; the planned shape is no longer "Phase 12 fills these
from a JWT" — it's "if a future deployment needs richer scoping,
this is the place to add it".

## Future (speculative)

These have come up enough to note, not enough to plan. Listed so contributors know they're on the radar; absence of a date means "no commitment".

- **Postpaid (batch mediation plane).** Today's `services/mediation` is TMF635 online mediation: single-event ingest, block-at-edge, no batch CDR collection. Postpaid would mean a parallel mediation pipeline that ingests CDR files, enriches against subscriber data, runs rerating windows. Substantial new domain — would justify its own version and probably its own service (`services/mediation-batch/`).
- **Multi-tenancy activation.** Every table has a `tenant_id` column already (seeded `'DEFAULT'`). Activating real multi-tenancy means routing requests by tenant claim, scoping queries per tenant, separate sequences per tenant. Phase 12+ once auth supports tenant claims.
- **Real CDR collection from network probes.** Currently out of scope per `CLAUDE.md` (channel/RAN concern). If a deployer ever wires a real network: a CDR-ingest service that parses Nokia NetAct / Ericsson EBM files into the existing `mediation.usage_event` shape.
- **EKS / Aurora Tier-3 deployment path.** ARCHITECTURE.md sketches an AWS deployment ladder (Tier 1: ECS Fargate single-AZ; Tier 2: small MVNO; Tier 3: scaled MVNO on EKS + Aurora). Tier 1 is buildable from the current Dockerfiles. Tier 3 needs schema-per-service Postgres extraction (the boundary is already enforced; the split is mechanical).
- **Customer-initiated chat in the self-serve portal.** Self-serve does signup, not support. A chat surface that escalates to a CSR is a real product, not a v0.x extension.
- **Webhooks out (TMF688).** Today's outbound MQ events are internal. Real customer integrations would want webhook subscriptions per tenant per event type.
- **Real eKYC integration.** Out of scope per doctrine — channel-layer concern. If a deployer ever wires Myinfo / Onfido / Jumio, the integration lives in the channel, not in BSS-CLI.
- **eSIM profile re-arm (`ESIM_PROFILE_REARM` SOM task).** v0.10's `/esim/<subscription_id>` is a read-only re-display of the LPA activation code minted at signup. Real GSMA SGP.22 redownload — operator-side trigger, SM-DP+ release / new activation-code mint, device re-bind — ships when the SM-DP+ adapter is real. Decomposition: new SOM task type, new `provisioning.rearm_esim_profile` policy, an `inventory.esim_profile.state == "released"` transition, a new portal route on top. See DECISIONS 2026-04-27.

## Non-goals

Restated from `CLAUDE.md` §"Scope boundaries" because new contributors keep asking:

- **eKYC.** Channel-layer concern. BSS-CLI receives a signed attestation, records it, enforces policy. No document capture, liveness, or vendor integration.
- **Customer-facing UI.** Mobile apps, USSD menus, retail POS — channel layer. The two portals (self-serve, CSR) are demos of the channel pattern, not customer-facing products.
- **Network elements.** No HLR/HSS, PCRF, OCS, SM-DP+ implementation. Provisioning-sim simulates these for demos; a real deployment wires real adapters.
- **Physical SIM logistics.** eSIM-only. No ICCID warehousing, no courier, no inventory beyond the seeded eSIM profile pool.
- **Real-time charging via Diameter.** Mediation is TMF635 online mediation, not OCS. No quota reservation protocol with the packet core.
- **Tax engines.** Inclusive SGD pricing. Vertex / Avalara are post-v0.x integrations.
- **Regulatory reporting.** IMDA / MCMC reports are extraction jobs against `audit.domain_event`, not built-in BSS features.
- **CRM-as-helpdesk.** Cases + tickets exist for telco state tracking, not as a Zendesk competitor. No SLA timer engine, no skill-based routing, no surveys.

If you're surprised by a non-goal, open a `DECISIONS.md` entry before writing the feature. Half the value of this list is making it expensive to silently grow scope.
