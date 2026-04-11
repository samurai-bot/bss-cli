# DECISIONS.md — BSS-CLI Architecture Decision Log

This file records non-obvious decisions. Every Claude Code session appends here when making a choice that isn't trivial. Future sessions read this to stay consistent.

## Format

```
## YYYY-MM-DD — Phase N — Title
**Context:** what prompted the decision
**Decision:** what we chose
**Alternatives:** what we rejected and why
**Consequences:** what this makes easier/harder
```

---

## Seed decisions (Phase 0, approved by Ck)

### 2026-04-11 — Phase 0 — Case/Ticket model is ServiceNow-shaped
**Context:** CRM cases and tickets can be flat (Zendesk-style) or hierarchical (ServiceNow-style).
**Decision:** Case is top-level container, Case has 1..N Tickets.
**Alternatives:** Zendesk-style — rejected because it doesn't match telco CRM reality (Siebel, Salesforce Comms Cloud).
**Consequences:** Closing a Case requires all child Tickets resolved. Natural context anchor for LLM actions.

### 2026-04-11 — Phase 0 — SOM uses proper hierarchical decomposition, minimal cardinality
**Context:** SOM modeling depth tradeoff.
**Decision:** Proper COM → SOM → CFS → RFS → Resource decomposition, but 1 CFS + 2 RFS per plan in v0.1.
**Alternatives:** Flat SOM — loses educational value. Multi-CFS per plan — v0.2.
**Consequences:** TMF641/638 shapes are real. State space tractable. Adding more CFS later is mechanical.

### 2026-04-11 — Phase 0 — Provisioning simulator has configurable failure scenarios
**Context:** Simulator fidelity level.
**Decision:** Time delays + per-task-type fault injection + "stuck" state for manual resolution.
**Alternatives:** Pure random failure (too simplistic); full fake NE (project within a project).
**Consequences:** Scenarios deliberately trigger failures. `bss trace` swimlanes show meaningful interactions.

### 2026-04-11 — Phase 0 — Write Policy doctrine (no raw CRUD)
**Context:** LLM write access without data corruption risk.
**Decision:** Every write flows through per-service policy layer. Router → Service → Policies → Repository → Event publisher.
**Alternatives:** Trust LLM + rollback (referential corruption is silent); DB constraints only (domain invariants don't map to constraints).
**Consequences:** More code per service. Every write phase adds policies to this file. LLM can be trusted with writes.

### 2026-04-11 — Phase 0 — RabbitMQ is the async plane, HTTP the sync plane
**Context:** Initial diagram conflated MQ with DB writes.
**Decision:** RabbitMQ = pub/sub between services for reactions. HTTP = direct calls for immediate answers. Postgres = per-service writes, not via MQ. Audit table + post-commit publish = simplified outbox.
**Alternatives:** Everything-via-events (loses sync call ergonomics); everything-via-HTTP (loses fanout and decoupling).
**Consequences:** Clear mental model. Services declare which plane each call uses. Replay via audit table.

### 2026-04-11 — Phase 0 — eSIM-only inventory
**Context:** Physical SIM involves warehousing, courier integration, activation-on-first-use semantics.
**Decision:** eSIM-only for v0.1. New provisioning task `ESIM_PROFILE_PREPARE`. SOM reserves MSISDN + eSIM profile atomically. Customer receives LPA activation code + ASCII QR code.
**Alternatives:** Physical + eSIM dual-track — eliminates from v0.1 as unnecessary complexity.
**Consequences:** No logistics layer. `inventory.esim_profile` table with ki_ref (NEVER raw Ki). Modern MVNO default.

### 2026-04-11 — Phase 0 — eKYC is a channel-layer concern
**Context:** eKYC involves document capture, liveness, biometrics, government integration — all jurisdiction-specific.
**Decision:** BSS-CLI receives signed KYC attestations via `customer.attest_kyc`. Document numbers stored as SHA-256 hashes. Full plaintext lives in the attesting system or nowhere. Channel layer (mobile app, portal) runs the actual eKYC flow with Myinfo/Jumio/Onfido.
**Alternatives:** Build eKYC into CRM — makes BSS jurisdiction-coupled and instantly obsolete when crossing borders.
**Consequences:** Clean separation of concerns. `kyc_status` column on customer, `customer_identity` table for attestation. Policy `order.create.requires_verified_customer` enforceable via env flag.

### 2026-04-11 — Phase 0 — Inventory domain hosted inside CRM service (v0.1)
**Context:** Inventory could be a separate service or embedded.
**Decision:** MSISDN + eSIM pools live inside CRM service as a separate domain (own schema, repositories, policies). Not a separate container in v0.1.
**Alternatives:** 11th service — adds network hop in critical path, adds ~150MB RAM, saves almost nothing operationally.
**Consequences:** 10 containers total. Inventory is extractable in v0.2 if needed — schema boundary is already enforced.

### 2026-04-11 — Phase 0 — Single Postgres instance, schema-per-domain
**Context:** 11 schemas could be one instance or many.
**Decision:** ONE PostgreSQL 16 instance with 11 schemas. Each service has its own `BSS_DB_URL` and uses only its own schema.
**Alternatives:** One instance per service — blows RAM budget (~4.4GB), operational complexity too high for v0.1.
**Consequences:** Simpler ops, simpler outbox pattern, fits in 4GB. Future split by schema is mechanical — no service code changes.

### 2026-04-11 — Phase 0 — Container structure: 10 services, infra optional
**Context:** How to package for deployment.
**Decision:** Default `docker-compose.yml` contains ONLY 10 BSS services. Separate `docker-compose.infra.yml` brings up Postgres, RabbitMQ, Metabase for all-in-one dev/demo. Most operators bring their own managed infra.
**Alternatives:** Single compose with everything — forces Postgres/MQ even when deployer has managed services.
**Consequences:** BYOI is the default shape. All-in-one is opt-in via `-f docker-compose.infra.yml`. Maps cleanly to ECS/EKS where each service is a task/pod.

### 2026-04-11 — Phase 0 — auth_context abstraction in every service for Phase 12 readiness
**Context:** v0.1 ships without auth; retrofitting auth later risks touching every service.
**Decision:** Every service has `app/auth_context.py` that returns a hardcoded `AuthContext(actor='system', tenant='DEFAULT', roles=['admin'], permissions=['*'])`. All policies and tool dispatches read from `auth_context.current()`. Phase 12 changes only this one module per service plus middleware.
**Alternatives:** Retrofit when needed — would touch every policy function and every router.
**Consequences:** ~30 minutes added to Phase 3 reference slice. Phase 12 becomes a decorator-layer concern.

### 2026-04-11 — Phase 0 — Runbook RAG deferred to Phase 11
**Context:** LLM procedural knowledge (runbooks) needs a knowledge base.
**Decision:** v0.1 ships with `docs/runbooks/` directory seeded with 3-4 markdown files but NO embedding/retrieval. Phase 11 adds `pgvector` extension to existing Postgres, `knowledge` schema, `knowledge.search` tool. BGE-small for embeddings (384-dim, local, PDPA-safe).
**Alternatives:** Dedicated vector DB (Qdrant) — extra container, blows footprint. LLM Wiki pattern — version control is weaker than git.
**Consequences:** Zero v0.1 scope cost. Runbook content can be drafted in parallel to code. Phase 11 is additive.

### 2026-04-11 — Phase 0 — AWS deployment path: ECS Fargate for Tier 1/2, EKS for Tier 3
**Context:** MVNO deployability on AWS.
**Decision:** v0.1 containers are ECS-Fargate-ready out of the box. Tier 1 (~$400/mo) is a direct compose→ECS translation. Tier 2 (~$1000/mo) adds Multi-AZ RDS, active/standby Amazon MQ, min 2 tasks per service. Tier 3 (100k+ subs, ~$5000/mo) switches to EKS + Aurora + MSK.
**Alternatives:** EKS from day 1 — overkill for small MVNO, higher operational burden.
**Consequences:** Zero v0.1 code changes needed for AWS Tier 1. Phase 12 (auth) is the gating dependency for Tier 2 (production).

---

## Initial policy catalog (seed — expand per phase)

### CRM — customer + KYC
- `customer.create.email_unique` — globally unique email across active customers
- `customer.create.requires_contact_medium` — at least one email OR phone
- `customer.close.no_active_subscriptions`
- `customer.attest_kyc.customer_exists`
- `customer.attest_kyc.attestation_signature_valid` — stub in v0.1
- `customer.attest_kyc.document_hash_unique_per_tenant`

### CRM — case
- `case.open.customer_must_be_active`
- `case.transition.valid_from_state`
- `case.close.requires_all_tickets_resolved`
- `case.close.requires_resolution_code`
- `case.add_note.case_not_closed`

### CRM — ticket
- `ticket.open.requires_customer_or_case`
- `ticket.assign.agent_must_be_active`
- `ticket.transition.valid_from_state`
- `ticket.resolve.requires_resolution_notes`
- `ticket.cancel.not_if_resolved_or_closed`

### Inventory
- `msisdn.reserve.status_must_be_available`
- `esim.reserve.status_must_be_available`
- `esim.release.only_if_reserved_or_assigned`

### Payment
- `payment_method.add.customer_exists`
- `payment_method.add.customer_active_or_pending`
- `payment_method.add.card_not_expired`
- `payment_method.add.at_most_n_methods`
- `payment_method.remove.not_last_if_active_subscription`
- `payment.charge.method_active`
- `payment.charge.positive_amount`
- `payment.charge.customer_matches_method`

### COM
- `order.create.customer_active_or_pending`
- `order.create.requires_cof`
- `order.create.requires_verified_customer` — gated by `BSS_REQUIRE_KYC` env var, default OFF in v0.1
- `order.create.offering_sellable`
- `order.cancel.forbidden_after_som_started`
- `order.transition.valid_from_state`

### SOM
- `service_order.create.requires_parent_order`
- `service_order.create.mapping_exists`
- `service.activate.requires_all_rfs_activated`
- `service.terminate.releases_msisdn_and_esim`
- `service.transition.valid_from_state`

### Provisioning
- `provisioning_task.retry.max_attempts`
- `provisioning.resolve_stuck.requires_note`
- `provisioning.set_fault_injection.admin_only`

### Subscription
- `subscription.create.requires_customer`
- `subscription.create.requires_payment_success`
- `subscription.create.msisdn_and_esim_reserved`
- `subscription.vas_purchase.requires_active_cof`
- `subscription.vas_purchase.vas_offering_sellable`
- `subscription.vas_purchase.not_if_terminated`
- `subscription.renew.only_if_active_or_blocked`
- `subscription.terminate.releases_msisdn`
- `subscription.terminate.recycles_esim`
- `subscription.terminate.cancels_pending_vas`

### Billing
- `bill.issue.subscription_exists`
- `bill.issue.period_not_already_billed`

### Usage / Mediation / Rating
- `usage.record.subscription_must_exist`
- `usage.record.subscription_must_be_active` — blocked → reject at ingress
- `usage.record.positive_quantity`
- `usage.record.valid_event_type`
- `usage.record.msisdn_belongs_to_subscription`
- `rating.tariff_must_exist_for_offering`

---

## Running log

_Claude Code appends below this line as phases progress._
