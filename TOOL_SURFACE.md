# TOOL_SURFACE.md — BSS-CLI LLM Tool Surface (v3)

The LangGraph orchestrator exposes ~65 tools. Every tool is a thin async function that calls a `bss-clients` method. **Tools contain no business logic.** The supervisor handles retries, planning, and error recovery.

Every write tool goes through the service's policy layer. A tool call that violates a policy returns a structured `PolicyViolation` observation — the LLM reads the `rule` field and can retry or ask the user.

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

## Usage tools

| Tool | Type | Description |
|---|---|---|
| `usage.simulate` | create | Primary way for LLM/scenario to inject usage |
| `usage.history` | read | |

## Billing tools

| Tool | Type | Description |
|---|---|---|
| `billing.get_account` | read | |
| `billing.list_bills` | read | |
| `billing.get_bill` | read | |
| `billing.get_current_period` | read | Period summary |

## Operational / observability tools

| Tool | Type | Description |
|---|---|---|
| `clock.now` | read | May be frozen for scenarios |
| `clock.advance` | update | Advance by duration |
| `clock.freeze` | update | |
| `clock.unfreeze` | update | |
| `trace.get` | read | ASCII swimlane (Phase 11+) |
| `trace.for_order` | read | |
| `trace.for_subscription` | read | |
| `events.list` | read | Query `audit.domain_event` |
| `agents.list` | read | |

## Knowledge tools (post-v0.1, Phase 11)

| Tool | Type | Description |
|---|---|---|
| `knowledge.search` | read | RAG over `docs/runbooks/` indexed into pgvector |
| `knowledge.get_document` | read | Full runbook by slug |

Not in v0.1 but reserved in the tool namespace.

## Admin tools (CLI-only, not LLM-exposed)

| Tool | Type | Description |
|---|---|---|
| `admin.reset_operational_data` | destructive | Scenario runner only |
| `admin.release_stuck_msisdn` | destructive | Emergency fix |
| `admin.release_stuck_esim` | destructive | Emergency fix |
| `admin.force_subscription_state` | destructive | Heavily audited |

---

## Tool count

- Customer + KYC + interaction + case + ticket: **19**
- Inventory: **4**
- Catalog: **4**
- Payment: **6**
- Order (COM): **5**
- SOM: **4**
- Provisioning: **5**
- Subscription: **7**
- Usage: **2**
- Billing: **4**
- Ops/observability: **9**
- Admin: **4** (not LLM-exposed)

**Total LLM-exposed: ~65 tools.** Up from ~62 in v2 (+2 KYC, +4 inventory read, +1 eSIM activation getter).

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
