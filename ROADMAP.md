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
| **v0.6.0** | *in progress* | Maintenance + polish. Docs sweep (README, ARCHITECTURE, CONTRIBUTING, ROADMAP, screenshots). Renderer polish on 5 hero ASCII renderers. Tech-debt sweep (catalog reorg, Dockerfile evaluation, doctrine grep guard, TOOL_SURFACE reconciliation, ship-criteria re-measurement). No new features. |

## Near-term (post-v0.6)

These have spec drafts or are explicitly tracked in `DECISIONS.md`. Versioning is tentative.

### Phase 11 — Knowledge / RAG

`knowledge.search` + `knowledge.get_document` tools backed by pgvector indexing of `docs/runbooks/`. Lets the LLM ground answers on the project's own operational knowledge — *"how do I rotate the BSS_API_TOKEN?"* returns the runbook content rather than a hallucinated procedure. Same Postgres instance, new `knowledge` schema. Documented as a Phase 11 backlog item since v0.1; the index + tools land in v0.7 (tentative) once a use case bigger than the runbook surface justifies it.

### Phase 11 — Dockerfile workspace migration

DECISIONS.md 2026-04-11 documented the per-service Dockerfile `sed` workaround. v0.6 evaluates the current `uv` version's workspace-in-Docker support empirically; the outcome is binary (migrate to a shared template OR re-defer with a fresh DECISIONS entry). If re-deferred in v0.6, the next attempt is post-v0.7.

### Metrics-via-OTel decision

v0.2 wired distributed tracing. Metrics (counters, histograms) currently go to structlog and aren't exported to a Prometheus / OTel-collector pipeline. Open question: do we add OTel metrics export alongside the existing trace export, or rely on Jaeger's span-derived metrics? Decision pending; tracked for v0.7+.

### Billing read-layer (TMF678)

DECISIONS.md 2026-04-13 deferred billing to v0.2. Skipped in v0.2-v0.5. Formally still planned: read-only view layer over `payment.payment_attempt`, statement generation, `/customerBill` TMF678 endpoints. Port 8009 reserved. No dunning, no credit extension — bundled-prepaid doesn't need them. Prioritized when an analytics/reporting use case asks for it.

## Phase 12 — Authentication & RBAC

The big post-portals piece. Spec exists in `CLAUDE.md` already.

- **Service-to-service:** OAuth2 client credentials, short-lived JWTs via `bss-clients`. Replaces the v0.3 shared admin token.
- **Human-to-system:** OAuth2 Authorization Code + PKCE through a new `services/auth` backed by Keycloak / Cognito / Entra. Replaces both portals' stub mechanisms (CSR portal stub login, self-serve portal no-auth).
- **8 coarse roles:** csr, senior_agent, billing_analyst, provisioning_engineer, supervisor, admin, auditor, system. Permissions derived 1:1 from tool names; the policy layer reads from `auth_context.current().role`.
- **Per-principal rate limiting** at the middleware level.
- **Resource scoping** via `tenant_id` and `customer_segment` claims.

`auth_context.py` has been in every service since Phase 3 specifically to support this swap. Phase 12 is the change per service: the middleware swaps from token-comparison to JWT-validation; `auth_context.current()` reads claims from the JWT instead of headers; business logic stays untouched.

This is the single largest post-v0.6 piece. Spec lives in `CLAUDE.md` §"Phase 12 model"; full version spec drafted only when the implementation phase begins.

## Future (speculative)

These have come up enough to note, not enough to plan. Listed so contributors know they're on the radar; absence of a date means "no commitment".

- **Postpaid (batch mediation plane).** Today's `services/mediation` is TMF635 online mediation: single-event ingest, block-at-edge, no batch CDR collection. Postpaid would mean a parallel mediation pipeline that ingests CDR files, enriches against subscriber data, runs rerating windows. Substantial new domain — would justify its own version and probably its own service (`services/mediation-batch/`).
- **Multi-tenancy activation.** Every table has a `tenant_id` column already (seeded `'DEFAULT'`). Activating real multi-tenancy means routing requests by tenant claim, scoping queries per tenant, separate sequences per tenant. Phase 12+ once auth supports tenant claims.
- **Real CDR collection from network probes.** Currently out of scope per `CLAUDE.md` (channel/RAN concern). If a deployer ever wires a real network: a CDR-ingest service that parses Nokia NetAct / Ericsson EBM files into the existing `mediation.usage_event` shape.
- **EKS / Aurora Tier-3 deployment path.** ARCHITECTURE.md sketches an AWS deployment ladder (Tier 1: ECS Fargate single-AZ; Tier 2: small MVNO; Tier 3: scaled MVNO on EKS + Aurora). Tier 1 is buildable from the current Dockerfiles. Tier 3 needs schema-per-service Postgres extraction (the boundary is already enforced; the split is mechanical).
- **Customer-initiated chat in the self-serve portal.** Self-serve does signup, not support. A chat surface that escalates to a CSR is a real product, not a v0.x extension.
- **Webhooks out (TMF688).** Today's outbound MQ events are internal. Real customer integrations would want webhook subscriptions per tenant per event type.
- **Real eKYC integration.** Out of scope per doctrine — channel-layer concern. If a deployer ever wires Myinfo / Onfido / Jumio, the integration lives in the channel, not in BSS-CLI.

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
