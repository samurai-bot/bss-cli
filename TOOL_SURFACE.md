# TOOL_SURFACE.md — BSS-CLI LLM Tool Surface (v3)

The LangGraph orchestrator exposes ~65 tools. Every tool is a thin async function that calls a `bss-clients` method. **Tools contain no business logic.** The supervisor handles retries, planning, and error recovery.

Every write tool goes through the service's policy layer. A tool call that violates a policy returns a structured `PolicyViolation` observation — the LLM reads the `rule` field and can retry or ask the user.

**v0.9 audit attribution.** Every tool's audit row in `audit.domain_event` now carries a `service_identity` column resolved by the BSS perimeter middleware from the validated `X-BSS-API-Token`. Operators filtering "which surface initiated this write?" can pivot on `service_identity` directly: `default` for orchestrator / CSR / scenario callers, `portal_self_serve` for self-serve portal callers (when the v0.11 portal chat surface uses `astream_once(service_identity=...)`), `partner_<name>` for future partner integrations. The tools themselves are unchanged — attribution happens at the perimeter, transparent to tool implementations.

## Tool type legend

- **read** — free, no permission gate (post-auth: still auditable)
- **create** — policy-gated
- **update** — policy-gated
- **destructive** — requires `--allow-destructive` CLI flag; LLM receives clear error if flag not set

---

## Customer tools (CRM)

| Tool | Type | Description |
|---|---|---|
| `customer.create` | create | Create a customer with name + at least one contact medium |
| `customer.get` | read | Get customer with contact mediums and KYC status |
| `customer.list` | read | List customers with filters (state, name_contains) |
| `customer.find_by_msisdn` | read | Resolve a phone number to its owning customer (v0.5+; CSR portal search) |
| `customer.update_contact` | update | Update primary contact medium |
| `customer.add_contact_medium` | create | Add additional contact |
| `customer.remove_contact_medium` | destructive | Remove contact medium |
| `customer.close` | destructive | Close customer account |

## KYC tools (CRM)

| Tool | Type | Description |
|---|---|---|
| `customer.attest_kyc` | create | Channel layer submits signed KYC attestation |
| `customer.get_kyc_status` | read | Read KYC state and expiry |

**Architectural note:** BSS-CLI does NOT perform eKYC. The channel layer (mobile app, web portal) runs the eKYC flow with a vendor (Myinfo, Jumio, Onfido), obtains a signed attestation, and submits it via `customer.attest_kyc`. BSS-CLI records the attestation and enforces `order.create.requires_verified_customer` policy.

## Interaction tools (CRM)

| Tool | Type | Description |
|---|---|---|
| `interaction.log` | create | Explicit interaction entry (rarely needed — auto-logged) |
| `interaction.list` | read | Interaction history for a customer |

Every CLI/LLM action that hits a write tool automatically creates an `interaction` row via CRM's auto-logging decorator, keyed on `X-BSS-Channel` and `X-BSS-Actor` headers. The LLM doesn't need to call `interaction.log` in normal workflows.

## Case tools (CRM)

| Tool | Type | Description |
|---|---|---|
| `case.open` | create | Open a new case |
| `case.get` | read | Case with child tickets and notes |
| `case.list` | read | Filter by customer, state, assigned agent |
| `case.add_note` | create | Add internal note |
| `case.update_priority` | update | |
| `case.transition` | update | Explicit state transition |
| `case.close` | update | Policy: all tickets resolved + resolution code |
| `case.show_transcript_for` | read | v0.12 — CSR-side: retrieve the chat transcript linked to a case (when set by `case.open_for_me`). |

## Ticket tools (CRM)

| Tool | Type | Description |
|---|---|---|
| `ticket.open` | create | Can link to case, order, subscription, service |
| `ticket.get` | read | With full state history |
| `ticket.list` | read | Filter by customer, case, state, agent |
| `ticket.assign` | update | Policy: agent must be active |
| `ticket.transition` | update | State machine compliance |
| `ticket.resolve` | update | Requires resolution notes |
| `ticket.close` | update | |
| `ticket.cancel` | destructive | Before resolution |

## Inventory tools (MSISDN + eSIM)

| Tool | Type | Description |
|---|---|---|
| `inventory.msisdn.list_available` | read | Support filters: prefix, golden patterns |
| `inventory.msisdn.get` | read | Status of a specific MSISDN |
| `inventory.esim.list_available` | read | Available eSIM profiles |
| `inventory.esim.get_activation` | read | Returns activation code + QR payload for assigned profile |

MSISDN and eSIM reservation are internal SOM operations — not exposed as direct LLM tools. The LLM only reads availability; reservation happens as a side effect of `order.create`.

## Catalog tools

| Tool | Type | Description |
|---|---|---|
| `catalog.list_offerings` | read | |
| `catalog.get_offering` | read | With prices, allowances, service mapping |
| `catalog.list_vas` | read | |
| `catalog.get_vas` | read | |
| `catalog.list_active_offerings` | read | v0.7 — time-bounded; lowest-active-price first |
| `catalog.get_active_price` | read | v0.7 — lowest-active-wins resolve at a moment |
| `catalog.add_offering` | create | v0.7 — admin only — not in LLM registry |
| `catalog.add_price` | create | v0.7 — admin only — not in LLM registry |
| `catalog.window_offering` | update | v0.7 — admin only — not in LLM registry |

## Payment tools

| Tool | Type | Description |
|---|---|---|
| `payment.add_card` | create | Customer must exist; tokenized server-side (sandbox only) |
| `payment.list_methods` | read | |
| `payment.remove_method` | destructive | Not last active method if active subscription |
| `payment.charge` | create | Rarely called by LLM — internal use |
| `payment.get_attempt` | read | |
| `payment.list_attempts` | read | |

## Commercial Order tools (COM)

| Tool | Type | Description |
|---|---|---|
| `order.create` | create | Customer must exist, have COF, be KYC-verified (if enforced) |
| `order.get` | read | With items and state history |
| `order.list` | read | |
| `order.cancel` | destructive | Only before SOM started |
| `order.wait_until` | read | Poll until state; used by scenario runner |

## Service Order tools (SOM)

| Tool | Type | Description |
|---|---|---|
| `service_order.get` | read | With items |
| `service_order.list_for_order` | read | |
| `service.get` | read | With state history, characteristics, MSISDN/ICCID |
| `service.list_for_subscription` | read | CFS + RFS tree |

SOM writes are internally triggered by COM events — no direct-create tool for service orders.

## Provisioning tools

| Tool | Type | Description |
|---|---|---|
| `provisioning.list_tasks` | read | Filter by service, state, time |
| `provisioning.get_task` | read | With history |
| `provisioning.resolve_stuck` | update | Requires note |
| `provisioning.retry_failed` | update | Subject to max_attempts policy |
| `provisioning.set_fault_injection` | update | Admin/scenario use |

## Subscription tools

| Tool | Type | Description |
|---|---|---|
| `subscription.get` | read | With bundle balances and renewal |
| `subscription.list_for_customer` | read | |
| `subscription.get_balance` | read | |
| `subscription.purchase_vas` | create | Charges COF, decrements block if exhausted |
| `subscription.terminate` | destructive | Releases MSISDN + recycles eSIM |
| `subscription.renew_now` | update | Manual renewal trigger |
| `subscription.get_esim_activation` | read | Returns LPA + QR for first-time display |
| `subscription.schedule_plan_change` | update | v0.7 — pivots plan + price at next renewal; no proration |
| `subscription.cancel_pending_plan_change` | update | v0.7 — clears pending pivot; idempotent |
| `subscription.migrate_to_new_price` | update | v0.7 — admin-only catalog price migration with notice |

## Usage tools

| Tool | Type | Description |
|---|---|---|
| `usage.simulate` | create | Primary way for LLM/scenario to inject usage |
| `usage.history` | read | |

## Operational / observability tools

| Tool | Type | Description |
|---|---|---|
| `clock.now` | read | May be frozen for scenarios |
| `clock.advance` | update | Advance by duration |
| `clock.freeze` | update | |
| `clock.unfreeze` | update | |
| `trace.get` | read | `(trace_id)` — fetch a Jaeger trace by 32-char hex ID. Returns summary `{traceId, spanCount, serviceCount, services, errorSpanCount, totalMs}`. Human-readable swimlane is `bss trace get <id>` on the CLI. |
| `trace.for_order` | read | `(order_id)` — resolve trace via `audit.domain_event` for an order, then fetch + summarize. Returns the same summary dict + `orderId`. |
| `trace.for_subscription` | read | `(subscription_id)` — same for subscriptions; returns summary + `subscriptionId`. |
| `events.list` | read | Query `audit.domain_event` |
| `agents.list` | read | |

## Billing tools — `(planned, deferred from v0.2)`

Reserved namespace; deferred from v0.2 to a future minor — see `DECISIONS.md` 2026-04-13 and `ROADMAP.md` "Near-term". Not in `TOOL_REGISTRY`.

| Tool | Type | Description |
|---|---|---|
| `billing.get_account` | read | `(planned)` Receipt account summary |
| `billing.list_bills` | read | `(planned)` Statement history |
| `billing.get_bill` | read | `(planned)` Single statement |
| `billing.get_current_period` | read | `(planned)` Current-period receipt summary |

## Knowledge tools — `(planned, Phase 11)`

Reserved namespace for the RAG-over-runbooks surface. Not in `TOOL_REGISTRY`.

| Tool | Type | Description |
|---|---|---|
| `knowledge.search` | read | `(planned, Phase 11)` RAG over `docs/runbooks/` indexed into pgvector |
| `knowledge.get_document` | read | `(planned, Phase 11)` Full runbook by slug |

## Customer-scoped wrappers — `(v0.12 chat profile)`

Curated subset of the registry exposed to the chat surface only. Each
wrapper binds ``customer_id`` from ``auth_context.current().actor`` —
**none accept a customer-bound parameter**. Greppable + startup
self-check (`_profiles.validate_profiles`). The chat route invokes
``astream_once(tool_filter="customer_self_serve", ...)`` so the LLM
sees only the entries below plus the public catalog reads
``catalog.list_vas``, ``catalog.list_active_offerings``,
``catalog.get_offering``.

v0.12 PR6 ships the escalation tool.

| Tool | Type | Description |
|---|---|---|
| `subscription.list_mine` | read | List the logged-in customer's subscriptions. |
| `subscription.get_mine` | read | Read one of the actor's subscriptions. Cross-customer attempts → `policy.subscription.not_owned_by_actor`. |
| `subscription.get_balance_mine` | read | Bundle balances for one of the actor's subscriptions. |
| `subscription.get_lpa_mine` | read | LPA activation-code bundle for the actor's eSIM (redownload assistance). |
| `usage.history_mine` | read | Usage history scoped to the actor's lines. Cross-customer subscription_id rejected. |
| `customer.get_mine` | read | The actor's own customer record. |
| `payment.method_list_mine` | read | The actor's cards on file. |
| `payment.charge_history_mine` | read | The actor's payment-attempt history. |
| `vas.purchase_for_me` | create | VAS top-up on one of the actor's subscriptions; charges default COF. |
| `subscription.schedule_plan_change_mine` | update | Schedule the next-renewal plan change on the actor's subscription. No proration. |
| `subscription.cancel_pending_plan_change_mine` | update | Clear a pending plan change. Idempotent. |
| `subscription.terminate_mine` | destructive | Terminate one of the actor's lines — releases MSISDN + eSIM. Gated by `safety.py`; `reason="customer_chat"` for audit attribution. |
| `case.open_for_me` | create | Open an escalation case on the actor's behalf for one of the five non-negotiable categories (fraud / billing_dispute / regulator_complaint / identity_recovery / bereavement, plus `other`). The transcript is hashed + persisted; the case carries the hash. |

## Admin tools — `(admin only, not in LLM registry)`

Exposed via `bss admin <verb>` and the scenario runner setup; intentionally NOT registered in `TOOL_REGISTRY` so the LLM can't reach them.

| Tool | Type | Description |
|---|---|---|
| `admin.reset_operational_data` | destructive | `(admin only)` Scenario runner setup hook |
| `admin.release_stuck_msisdn` | destructive | `(admin only)` Emergency fix |
| `admin.release_stuck_esim` | destructive | `(admin only)` Emergency fix |
| `admin.force_subscription_state` | destructive | `(admin only)` Heavily audited |

---

## Tool count (v0.6 re-tally)

Counted from the live `TOOL_REGISTRY` against this document; the
`test_registry_matches_tool_surface_md` test enforces consistency.

- Customer + KYC + interaction + case + ticket: **19**
- Inventory: **4**
- Catalog: **4**
- Payment: **6**
- Order (COM): **5**
- SOM: **2**
- Provisioning: **5**
- Subscription: **7**
- Service: **2**
- Usage: **2**
- Trace + observability: **5** (`trace.get`, `trace.for_order`, `trace.for_subscription`, `events.list`, `agents.list`)
- Clock: **4**

**Total LLM-exposed: 73 tools** (live in `TOOL_REGISTRY`).

**Documented but not registered (planned / non-tool):**
- 4 `billing.*` — `(planned)` reserved namespace, see ROADMAP near-term
- 2 `knowledge.*` — `(planned, Phase 11)` RAG surface
- 4 `admin.*` — `(admin only)` not exposed to the LLM
- (3 historical strays — `audit.domain_event`, `payment.payment_attempt`, `order.create.requires_verified_customer` — are tables / policies, not tools; clarified inline near their references rather than listed in the tool tables.)

**13 documented placeholder rows / 73 registered tools.** A reader scanning the tables should immediately tell live tools from planned/non-tool entries by the `(...)` status badge in the description column.

## Why this is still manageable

- Tools grouped by namespace — LLMs reason well about namespaces
- Most workflows use 3-6 tools end-to-end
- System prompt includes common workflow recipes as few-shot examples
- PolicyViolation errors are structured and self-explanatory

## Common workflows (for the system prompt)

**Customer signup (with KYC):**
```
customer.create
  → customer.attest_kyc  (channel has the attestation)
  → payment.add_card
  → order.create
  → order.wait_until(state=completed)
  → subscription.list_for_customer
  → subscription.get_esim_activation  (show QR)
```

**Diagnose "my data stopped working":**
```
subscription.get (check state)
  → if blocked: subscription.get_balance → offer VAS → subscription.purchase_vas
  → if active: service.list_for_subscription → provisioning.list_tasks → escalate if stuck
```

**Stuck provisioning investigation:**
```
order.get
  → service_order.list_for_order
  → provisioning.list_tasks(state=stuck)
  → provisioning.resolve_stuck  (if confirmed)  OR  ticket.open  (escalate)
```

**VAS top-up:**
```
subscription.get
  → catalog.list_vas
  → subscription.purchase_vas
```

## The system prompt principle

The LLM's system prompt must include:

1. The seven motto principles (what's impossible — no dunning, no proration, no eKYC)
2. The plan list (S, M, L — nothing else)
3. Common workflow recipes as few-shot examples
4. Policy violation response protocol: read the `rule`, understand the constraint, retry or ask
5. Channel context: the LLM operates on behalf of humans; KYC attestations come from the channel layer, never fabricated

The LLM is not expected to memorize all 65 tools. It reads the tool manifest at session start and plans accordingly.
