# Phase 9 — CLI + LLM Orchestrator + ASCII Renderers

> **The product face.** Everything before this phase is plumbing. This phase is what people see, so it's what breaks or sells the demo. Build the direct CLI first, then the LLM layer, then the renderers. Do not invert this order.

## Goal

The `bss` command. Typer CLI, LangGraph orchestrator, ~62 tools, and the first set of ASCII renderers. By end of phase:

```
$ bss "create Ck on plan M with card 4242 4242 4242 4242"
$ bss subscription show SUB-007
$ bss case list --customer CUST-007
$ bss ticket show TKT-101
$ bss                 # drops into REPL
```

## Deliverables

### 1. `cli/` — Typer CLI

```
cli/
├── bss_cli/
│   ├── __init__.py
│   ├── main.py              # Typer root
│   ├── config.py            # service URLs, LLM config — uses _REPO_ROOT pattern
│   ├── context.py           # channel/actor injection
│   ├── commands/
│   │   ├── customer.py      # create, list, show, update-contact
│   │   ├── case.py          # open, list, show, note, close
│   │   ├── ticket.py        # open, list, show, assign, ack, start, resolve, close
│   │   ├── catalog.py       # list, show
│   │   ├── payment.py       # add-card (dev tokenizer), list, show
│   │   ├── order.py         # create, list, show, cancel
│   │   ├── som.py           # service list, service show, service-order show
│   │   ├── subscription.py  # show, list, balance, vas, renew, terminate
│   │   ├── usage.py         # simulate, history
│   │   ├── billing.py       # bills, bill show, account
│   │   ├── prov.py          # tasks, resolve, retry, fault
│   │   ├── clock.py         # now, freeze, unfreeze, advance
│   │   ├── trace.py         # events (proxy to audit.domain_event for now)
│   │   ├── scenario.py      # runner stubs (populated in Phase 10)
│   │   ├── admin.py         # reset, force-*, release-msisdn
│   │   └── ask.py           # LLM entry point
│   ├── renderers/
│   │   ├── _utils.py
│   │   ├── subscription.py  # bundle bars, state, countdown (HERO)
│   │   ├── customer.py      # 360 view (HERO)
│   │   ├── case.py          # case with child tickets (HERO)
│   │   ├── ticket.py        # single ticket with history
│   │   ├── catalog.py       # plan comparison table (HERO)
│   │   ├── order.py         # order state + service decomposition tree (HERO)
│   │   └── esim.py          # eSIM activation card with QR ASCII (HERO)
│   └── repl.py              # interactive LLM REPL
├── pyproject.toml
└── README.md
```

Entry point: `bss = bss_cli.main:app`

`config.py` uses the `_REPO_ROOT` pattern from the Phase 3 chore fix so CLI reads `.env` regardless of invocation directory.

### 2. Command shape

Direct commands use explicit subcommands:

```
bss customer create --name Ck --email ck@example.com --card 4242424242424242
bss customer list --state active
bss customer show CUST-007

bss case open --customer CUST-007 --subject "Data not working" --category technical --priority high
bss case list --customer CUST-007
bss case show CASE-042

bss ticket open --case CASE-042 --type service_outage --subject "No data session"
bss ticket assign TKT-101 --agent AGT-004
bss ticket ack TKT-101
bss ticket start TKT-101
bss ticket resolve TKT-101 --notes "HLR re-provisioned; confirmed working"
bss ticket close TKT-101

bss order create --customer CUST-007 --offering PLAN_M
bss order show ORD-014

bss som service list --subscription SUB-007
bss subscription show SUB-007
bss subscription show SUB-007 --show-esim
bss subscription vas SUB-007 VAS_DATA_5GB

bss usage simulate --msisdn 90000005 --type data --quantity 1GB

bss prov tasks --service SVC-333
bss prov resolve PTK-444 --note "HLR manual intervention complete"
bss prov fault HLR_PROVISION fail_first_attempt --enable --probability 0.3

bss clock now
bss clock advance 30d

bss trace events --aggregate subscription --id SUB-007
```

Natural language mode:

```
bss ask "create Ck on plan M with card 4242 4242 4242 4242"
bss ask "show me Ck's bundle"
bss ask "Ck says his data stopped working, open a case and a technical ticket"
bss                 # REPL — persistent context across turns
```

### 3. `orchestrator/` — LangGraph agent

```
orchestrator/
├── bss_orchestrator/
│   ├── __init__.py
│   ├── graph.py             # LangGraph supervisor
│   ├── tools/
│   │   ├── __init__.py      # tool registry
│   │   ├── customer.py
│   │   ├── interaction.py
│   │   ├── case.py
│   │   ├── ticket.py
│   │   ├── catalog.py
│   │   ├── payment.py
│   │   ├── order.py
│   │   ├── som.py
│   │   ├── provisioning.py
│   │   ├── subscription.py
│   │   ├── usage.py
│   │   ├── billing.py
│   │   └── ops.py
│   ├── llm.py               # LiteLLM config → MiMo v2 Flash
│   ├── prompts.py
│   ├── safety.py            # destructive op gating
│   └── session.py           # REPL session state
├── litellm_config.yaml
└── pyproject.toml
```

### 4. Tool implementation pattern — dumb, thin, no retries

Every tool is a thin async wrapper over `bss-clients`. **No retries, no fallbacks, no business logic.** The supervisor handles retries and planning at the graph level.

```python
from bss_clients import SubscriptionClient

async def subscription_purchase_vas(subscription_id: str, vas_offering_id: str) -> dict:
    """Purchase a VAS for a subscription. Charges the customer's default payment method.

    Args:
        subscription_id: The subscription to top up, e.g. SUB-007
        vas_offering_id: The VAS product offering, e.g. VAS_DATA_5GB

    Returns:
        Updated subscription with new balance

    Raises:
        PolicyViolationFromServer: if policy check fails (with structured rule info)
    """
    async with SubscriptionClient() as client:
        return await client.purchase_vas(subscription_id, vas_offering_id)
```

Every tool must map 1:1 to an existing entry in `TOOL_SURFACE.md`. No drift, no invented tools, no "helper" tools that combine multiple ops.

### 5. Safety / destructive op gating

`safety.py`:

```python
DESTRUCTIVE_TOOLS = {
    "customer.close",
    "customer.remove_contact_medium",
    "case.cancel",
    "ticket.cancel",
    "payment.remove_method",
    "order.cancel",
    "subscription.terminate",
    "provisioning.set_fault_injection",  # admin-ish
    "admin.reset_operational_data",
    "admin.force_state",
}

def wrap_destructive(tool_fn, allow_destructive: bool):
    async def wrapped(**kwargs):
        if not allow_destructive:
            return {
                "error": "DESTRUCTIVE_OPERATION_BLOCKED",
                "message": f"Tool {tool_fn.__name__} requires --allow-destructive flag. "
                           f"Ask the user to re-run with this flag if they truly intend this operation.",
                "tool": tool_fn.__name__,
            }
        return await tool_fn(**kwargs)
    return wrapped
```

The supervisor sees the structured error and can abort cleanly or ask the user to reconfirm and rerun. This pattern mirrors `PolicyViolationFromServer` — structured error, not a stack trace.

### 6. System prompt — `prompts.py`

```python
SYSTEM_PROMPT = """You are the BSS-CLI orchestrator, operating a lightweight TMF-compliant BSS for a mobile prepaid telco.

## Core rules
1. Plans are S, M, L only. No other plans exist. Don't invent them.
2. Every customer must have a card on file before any subscription.
3. Mock card: any 16-digit number works unless it contains 'FAIL'.
4. Destructive operations require --allow-destructive. If blocked, report the error and ask the user.
5. Policy violations come back as structured errors with a `rule` field — read it, understand the constraint, then decide: retry with corrections, or ask the user.
6. Never fabricate IDs. If you don't know, call a read tool first.
7. Prefer one tool call at a time. Plan → call → observe → plan.
8. When an action affects a customer, the CRM policy layer will auto-log an interaction. You don't need to call interaction.log explicitly.
9. Current time comes from clock.now — don't assume.

## Common workflows

**Customer signup:**
  customer.create → payment.add_card → order.create → (wait for order.completed) → subscription.list_for_customer → subscription.get

**Check "why is service not working":**
  subscription.get (state?) → if blocked: subscription.get_balance → suggest VAS → if active but customer complains: ticket.open

**VAS top-up:**
  subscription.get → catalog.list_vas → subscription.purchase_vas

**Investigate stuck provisioning:**
  order.get → service_order.list_for_order → provisioning.list_tasks → provisioning.resolve_stuck (if user confirms) or ticket.open (escalate)

## Output style
- Terse. IDs and state, not paragraphs.
- When rendering results, delegate to the CLI renderer (return the IDs; the CLI will render).
- Don't explain what you're about to do — just do it and report what happened.
"""
```

Add 4-6 few-shot examples showing the common workflows above. Examples must show real IDs, real tool calls, real error handling on a `PolicyViolationFromServer`.

### 7. ASCII renderers

**Six hero renderers must exist and look right:**

1. **Subscription show (the hero hero).** Bundle bars, state, countdown.

```
┌─ Subscription SUB-007 ──────────────────────────────────────┐
│                                                              │
│  Customer:    Ck (CUST-007)                                 │
│  MSISDN:      9000 0005                                     │
│  Plan:        Standard (PLAN_M) — SGD 25/mo                 │
│  State:       ● ACTIVE                                       │
│  Activated:   2026-04-10 09:15                              │
│  Renews in:   23 days (2026-05-03)                          │
│                                                              │
│  ── Bundle ──────────────────────────────────────────────    │
│  Data    [████████████░░░░░░░░░░░░░░]  12.4 / 30.0 GB  41%  │
│  Voice   [──────────────────────────]  unlimited            │
│  SMS     [──────────────────────────]  unlimited            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

2. **Customer 360.** Status, contact, subscriptions, open cases with child tickets, recent interactions.

```
┌─ CUST-007  Ck  ─────────────────────────────────────────────┐
│  Status: ● active   since 2026-04-10                         │
│  Contact: ck@example.com · +65 9000 0005                     │
│                                                              │
│  ── Subscriptions (1) ─────────────────────────────────────  │
│  SUB-007  PLAN_M  active   MSISDN 90000005  bundle 41%       │
│                                                              │
│  ── Open Cases (1) ────────────────────────────────────────  │
│  CASE-042  "Data not working"       high    in_progress      │
│    └─ TKT-101  service_outage       high    assigned AGT-004 │
│                                                              │
│  ── Recent Interactions (3) ───────────────────────────────  │
│  2026-04-11 13:05  llm      create_customer                  │
│  2026-04-11 13:05  llm      add_payment_method               │
│  2026-04-11 13:06  llm      create_order PLAN_M              │
└──────────────────────────────────────────────────────────────┘
```

3. **Case show** with child tickets and notes.

```
┌─ CASE-042  "Data not working"  [in_progress]  high  ───────┐
│  Customer: CUST-007 Ck                                       │
│  Opened:   2026-04-11 13:15 by AGT-002 Bob                   │
│                                                              │
│  ── Tickets (2) ───────────────────────────────────────────  │
│  TKT-101  service_outage  in_progress  high  AGT-004 Dave    │
│  TKT-102  information     resolved     low   AGT-002 Bob     │
│                                                              │
│  ── Notes (1) ─────────────────────────────────────────────  │
│  [AGT-002 2026-04-11 13:18]  Customer reports no data since  │
│                              morning, voice works fine.      │
└──────────────────────────────────────────────────────────────┘
```

4. **Order show** with SOM decomposition tree.

```
┌─ ORD-014  PLAN_M  [completed]  ─────────────────────────────┐
│  Customer: CUST-007                                          │
│  Placed:   2026-04-11 13:05                                  │
│  Done:     2026-04-11 13:05 (+1.4s)                          │
│                                                              │
│  ── Service Order SO-022 [completed] ─────────────────────   │
│    └─ CFS SVC-033  MobileBroadband      activated            │
│         ├─ RFS SVC-034  DataBearer       activated           │
│         │     ├─ PTK-041 HLR_PROVISION   completed (0.5s)    │
│         │     └─ PTK-042 PCRF_POLICY     completed (0.3s)    │
│         ├─ RFS SVC-035  VoiceBearer      activated           │
│         │     └─ PTK-043 HLR_PROVISION   completed (0.5s)    │
│         └─ (CFS)  OCS_BALANCE_INIT       completed (0.2s)    │
│                                                              │
│  → Subscription SUB-007 activated                            │
└──────────────────────────────────────────────────────────────┘
```

5. **Catalog list** — three-column plan comparison.

```
┌─ Product Offerings ──────────────────────────────────────────┐
│                                                               │
│  ┌── PLAN_S  Lite ──┐  ┌── PLAN_M  Standard ─┐  ┌── PLAN_L  Max ─┐
│  │  SGD 10 /mo      │  │  SGD 25 /mo          │  │  SGD 45 /mo   │
│  │                  │  │                      │  │               │
│  │  Data    5 GB    │  │  Data    30 GB       │  │  Data   150GB │
│  │  Voice   100 min │  │  Voice   unlimited   │  │  Voice  unlim │
│  │  SMS     100     │  │  SMS     unlimited   │  │  SMS    unlim │
│  └──────────────────┘  └──────────────────────┘  └───────────────┘
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

6. **eSIM activation card** with QR ASCII.

```
┌─ eSIM Activation ────────────────────────────────────┐
│                                                       │
│  ICCID:    8910 1010 0000 0000 005                  │
│  IMSI:     525 01 0000 0005                         │
│  MSISDN:   9000 0005                                 │
│                                                       │
│  ┌─────────────────────────────┐                     │
│  │ ▓▓ ▓▓▓▓  ▓▓ ▓▓▓▓▓ ▓▓▓▓ ▓▓ │  Scan with phone    │
│  │ ▓▓▓▓ ▓▓  ▓▓▓▓ ▓▓ ▓▓ ▓▓▓▓▓ │  camera to install  │
│  │  ▓▓ ▓▓▓▓ ▓▓  ▓▓▓▓ ▓▓  ▓▓ │  eSIM                │
│  │ ▓▓▓▓▓ ▓▓ ▓▓▓▓▓ ▓▓ ▓▓▓ ▓▓ │                      │
│  └─────────────────────────────┘                     │
│                                                       │
│  Or enter manually:                                   │
│  LPA:1$smdp.bss-cli.local$A4B29F81XK22M7PQ           │
│                                                       │
└──────────────────────────────────────────────────────┘
```

Use the `qrcode` Python library with text output mode (`qrcode.QRCode(...).print_ascii()` or equivalent). ~20 lines of renderer code. Invoked via `bss subscription show SUB-xxx --show-esim` or automatically on first-time display in a scenario.

**Ticket show and prov task list** use simpler `rich.table.Table` renderers — not hero-tier but still must exist.

### 8. Channel injection

Every CLI command sets the `X-BSS-Channel` header when making HTTP calls through `bss-clients`:

- Direct CLI: `X-BSS-Channel: cli`, `X-BSS-Actor: cli-user`
- LLM mode: `X-BSS-Channel: llm`, `X-BSS-Actor: llm-mimo-v2-flash`
- Scenario runner (Phase 10): `X-BSS-Channel: scenario`, `X-BSS-Actor: scenario:<name>`

CRM's interaction auto-logging reads these headers (wired in Phase 4). Phase 9 just ensures the CLI sets them correctly via `bss-clients`' header-propagation hook.

## Test strategy

Phase 4 lessons apply: httpx-equivalent testing through Typer's `CliRunner`, no direct function calls that bypass the CLI layer.

### Required test files

- `test_cli_customer_commands.py` — `CliRunner` tests for every customer subcommand
- `test_cli_order_flow.py` — `bss order create` → `bss order show` → `bss subscription show` end-to-end
- `test_renderers_snapshot.py` — snapshot tests for each hero renderer against canned input (prevents accidental format drift)
- `test_orchestrator_tools.py` — every tool in `orchestrator/tools/` has a positive + policy-violation test
- `test_orchestrator_safety.py` — destructive tools blocked without flag, succeed with flag
- `test_orchestrator_graph.py` — simple two-step plan (create customer → add card), verify correct tool sequence
- `test_llm_policy_violation_handling.py` — trigger a policy violation, confirm the LLM reads the structured error and either retries with correction or asks the user
- `test_channel_injection.py` — every CLI invocation results in the right `X-BSS-Channel` and `X-BSS-Actor` on outbound calls
- `test_repl_session_state.py` — REPL retains context across turns (customer_id mentioned once, referenced later)

### LLM mocking strategy

Unit tests for the graph use `LiteLLM`'s mock mode or a deterministic fake model that returns pre-programmed tool call sequences. Don't hit a real model in CI tests — too slow, non-deterministic, costs money. One or two smoke tests against the real MiMo model are fine, marked `@pytest.mark.integration` and skipped by default.

## Verification checklist

- [ ] `bss --help` lists all command groups
- [ ] `bss customer create ...` works directly (no LLM)
- [ ] `bss order create ...` works, triggering Phase 7 end-to-end flow
- [ ] `bss subscription show SUB-xxx` renders the hero view correctly (check against snapshot)
- [ ] `bss customer show CUST-xxx` renders the 360 view (snapshot)
- [ ] `bss case show CASE-xxx` renders with child tickets (snapshot)
- [ ] `bss order show ORD-xxx` renders with SOM decomposition tree (snapshot)
- [ ] `bss catalog list` renders the 3-column plan comparison (snapshot)
- [ ] `bss subscription show SUB-xxx --show-esim` renders the eSIM activation card with QR ASCII
- [ ] `bss ask "create a customer named Ck on plan M with card 4242 4242 4242 4242"` produces the same end-to-end result as direct commands
- [ ] `bss ask "show me Ck's bundle"` returns the ASCII render
- [ ] `bss ask "terminate Ck's subscription"` is blocked with `DESTRUCTIVE_OPERATION_BLOCKED`
- [ ] `bss ask "terminate Ck's subscription" --allow-destructive` succeeds
- [ ] `bss` with no args opens REPL; context persists across turns (mention customer once, refer later)
- [ ] Deliberate policy violation ("close CASE-xxx with open tickets") is reported cleanly by the LLM with the rule ID
- [ ] LLM tool calls log structured JSON to stdout/file
- [ ] Every CLI action shows up as an interaction in the relevant customer's log (`bss customer show` → recent interactions section populated)
- [ ] `grep -rn "retry\|backoff" orchestrator/bss_orchestrator/tools/` returns **zero hits** (tools stay dumb)
- [ ] `make test` — all suites green including CLI and orchestrator
- [ ] Campaign OS schemas untouched

## Out of scope

- `bss trace` ASCII swimlane (Phase 11 — needs OTel)
- Streaming token output in REPL (nice-to-have)
- Tab completion for IDs
- Color themes
- Save/load REPL sessions
- Real model in CI (integration tests only)

## Session prompt

> Read `CLAUDE.md`, `ARCHITECTURE.md`, `TOOL_SURFACE.md` (this is the source of truth for tools), `DECISIONS.md`, `phases/PHASE_07.md` (end-to-end flow), `phases/PHASE_08.md` (usage pipeline), and `phases/PHASE_09.md`.
>
> Before writing any code, produce a plan that includes:
>
> 1. **Typer command inventory** — every command group and subcommand with its arguments. Confirm this maps to the services built in Phases 3-8. No invented commands.
>
> 2. **LangGraph tool inventory** — every tool with its function signature and doc string. Confirm 1:1 mapping with `TOOL_SURFACE.md` entries. Flag any gaps.
>
> 3. **Renderer mockups** — paste the ASCII mockup for each of the 6 hero renderers (subscription, customer 360, case, order decomposition, catalog, eSIM activation). These are the visual contract for the phase. Put them in `DECISIONS.md` under Phase 9.
>
> 4. **System prompt + few-shot examples** — paste the full system prompt and 4-6 few-shot examples showing (a) customer signup, (b) VAS top-up on blocked sub, (c) investigate stuck provisioning, (d) handle a policy violation gracefully.
>
> 5. **Safety wrapper** — paste the `DESTRUCTIVE_TOOLS` set and the `wrap_destructive` function.
>
> 6. **Channel injection mechanism** — confirm `bss-clients` propagates `X-BSS-Channel` and `X-BSS-Actor` from the CLI's `auth_context.current()`. No hardcoded headers in individual tools.
>
> 7. **LLM mocking strategy** — confirm unit tests use a deterministic fake model, not real MiMo. Integration tests marked `@pytest.mark.integration` and skipped by default.
>
> 8. **REPL session state** — paste the session object showing how captured IDs persist across turns.
>
> 9. **Tool dumbness contract** — confirm every tool is a thin async wrapper with no retries, no fallbacks, no business logic. Supervisor handles retries at the graph level. Paste one tool as an example of the canonical shape.
>
> Wait for my approval before writing any code.
>
> After I approve, implement in this order:
> 1. Direct Typer commands (no LLM) — every command works end-to-end
> 2. Channel injection wire-through via `bss-clients` hook
> 3. ASCII renderers — subscription first (hero), then customer 360, case, order, catalog, eSIM
> 4. Orchestrator tools — one file per domain, 1:1 with TOOL_SURFACE.md
> 5. Safety wrapper + destructive gating
> 6. LangGraph supervisor + system prompt + few-shot examples
> 7. REPL with session state
> 8. Integration tests including LLM path with deterministic fake model
>
> Run full verification checklist. Do not commit.

## The trap

**Build the direct CLI first.** If `bss customer create` doesn't work explicitly, the LLM version won't save you — it'll just obscure the bug. Never invert this order.

**Tools stay dumb.** If you catch yourself adding retry logic to a tool, stop. That's supervisor territory. Grep check: `grep -rn "retry\|backoff\|except" orchestrator/bss_orchestrator/tools/` should find only the minimum required error re-raising, no retry loops.

**Don't try to make the LLM "smart".** It only needs to be good enough to chain 3-5 tool calls with clean error handling. A dumb-but-reliable orchestrator beats a clever one that fabricates IDs. Catch fabrication early: if the LLM proposes a tool call with an ID that wasn't in any prior tool result, reject the call and loop back with the error.

**Snapshot-test the renderers.** They're easy to break accidentally (someone changes a field name in the TMF schema, the renderer silently renders garbage). Snapshot tests catch drift immediately.

**Channel injection is not optional.** If CLI actions don't show up in CRM's interaction log, the audit trail is broken and the "this customer called support, this agent did X" story fails at the demo. Test explicitly.
