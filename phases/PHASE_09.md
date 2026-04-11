# Phase 9 — CLI + LLM Orchestrator + ASCII Renderers

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
│   ├── config.py            # service URLs, LLM config
│   ├── context.py           # channel/actor injection
│   ├── commands/
│   │   ├── customer.py      # create, list, show, update-contact
│   │   ├── case.py          # open, list, show, note, close
│   │   ├── ticket.py        # open, list, show, assign, resolve, close
│   │   ├── catalog.py       # list, show
│   │   ├── payment.py       # add-card, list, show
│   │   ├── order.py         # create, list, show, cancel
│   │   ├── som.py           # service list, service show, service-order show
│   │   ├── subscription.py  # show, list, balance, vas, renew, terminate
│   │   ├── usage.py         # simulate, history
│   │   ├── billing.py       # bills, bill show, account
│   │   ├── prov.py          # tasks, resolve, retry, fault
│   │   ├── clock.py         # now, freeze, unfreeze, advance
│   │   ├── trace.py         # events (proxy to audit.domain_event for now)
│   │   ├── scenario.py      # runner (populated in Phase 10)
│   │   ├── admin.py         # reset, force-*, release-msisdn
│   │   └── ask.py           # the LLM entry point
│   ├── renderers/
│   │   ├── _utils.py
│   │   ├── subscription.py  # bundle bars, state, countdown (hero)
│   │   ├── customer.py      # 360 view
│   │   ├── case.py          # case with child tickets
│   │   ├── ticket.py        # single ticket with history
│   │   ├── catalog.py       # plan comparison table
│   │   ├── order.py         # order state + service decomposition tree
│   │   └── esim.py          # eSIM activation card with QR ASCII
│   └── repl.py              # interactive LLM REPL
├── pyproject.toml
└── README.md
```

Entry point: `bss = bss_cli.main:app`

### Command shape

Direct commands use explicit subcommands:
```
bss customer create --name Ck --email ck@example.com --card 4242...
bss customer list --state active
bss customer show CUST-007
bss case open --customer CUST-007 --subject "Data not working" --category technical --priority high
bss case list --customer CUST-007
bss case show CASE-042
bss ticket open --case CASE-042 --type service_outage --subject "No data session"
bss ticket assign TKT-101 --agent AGT-004
bss ticket resolve TKT-101 --notes "HLR re-provisioned; confirmed working"
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

Natural language mode invoked via `bss ask "..."` or bare `bss` → REPL:
```
bss ask "create Ck on plan M with card 4242 4242 4242 4242"
bss ask "show me Ck's bundle"
bss ask "Ck says his data stopped working, open a case and a technical ticket"
bss                 # REPL
```

### 2. `orchestrator/` — LangGraph agent

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

### 3. Tool implementation pattern

Every tool is a thin async wrapper:
```python
from bss_clients import SubscriptionClient
from langgraph.prebuilt import ToolExecutor

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

Tools contain no retries, no fallbacks, no business logic. The supervisor handles retries and planning.

### 4. Safety / destructive op gating

`safety.py`:
```python
DESTRUCTIVE_TOOLS = {
    "customer.close",
    "customer.remove_contact_medium",
    "case.cancel",      # not exposed in v0.1 but reserved
    "ticket.cancel",
    "payment.remove_method",
    "order.cancel",
    "subscription.terminate",
    "provisioning.set_fault_injection",  # admin-ish
}

def wrap_destructive(tool_fn, allow_destructive: bool):
    async def wrapped(**kwargs):
        if not allow_destructive:
            return {
                "error": "DESTRUCTIVE_OPERATION_BLOCKED",
                "message": f"Tool {tool_fn.__name__} requires --allow-destructive flag. "
                           f"Ask the user to re-run with this flag if they truly intend this operation.",
                "tool": tool_fn.__name__
            }
        return await tool_fn(**kwargs)
    return wrapped
```

The supervisor sees the structured error and can either abort cleanly or ask the user to reconfirm and rerun.

### 5. System prompt

`prompts.py`:
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

Add 4-6 few-shot examples showing the common workflows above.

### 6. ASCII renderers

**Subscription show (hero):**
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

**Customer 360:**
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

**Case show (with children):**
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

**Order show (with SOM decomposition):**
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

**Catalog list:**
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

**Ticket show, Prov task list:** simpler table renderers using `rich.table.Table`.

**eSIM Activation (new in v3):**
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

Use the `qrcode` Python library with the `qrcode.image.pure.PyPNGImage` backend or the built-in text output mode. ~20 lines of renderer code. Invoked via `bss subscription show SUB-xxx --show-esim` or automatically on first-time display.

### 7. Channel injection

Every CLI command sets the `X-BSS-Channel` header when making HTTP calls:
- Direct CLI: `X-BSS-Channel: cli`, `X-BSS-Actor: cli-user`
- LLM mode: `X-BSS-Channel: llm`, `X-BSS-Actor: llm-mimo-v2-flash`
- Scenario runner (Phase 10): `X-BSS-Channel: scenario`, `X-BSS-Actor: scenario:<name>`

CRM's interaction auto-logging reads these headers.

## Verification checklist

- [ ] `bss --help` lists all command groups
- [ ] `bss customer create ...` works directly (no LLM)
- [ ] `bss order create ...` works, triggering Phase 7 end-to-end flow
- [ ] `bss subscription show SUB-xxx` renders the hero view correctly
- [ ] `bss customer show CUST-xxx` renders the 360 view
- [ ] `bss case show CASE-xxx` renders with child tickets
- [ ] `bss order show ORD-xxx` renders with SOM decomposition tree
- [ ] `bss catalog list` renders the 3-column plan comparison
- [ ] `bss ask "create a customer named Ck on plan M with card 4242 4242 4242 4242"` produces the same end-to-end result
- [ ] `bss ask "show me Ck's bundle"` returns the ASCII render
- [ ] `bss ask "terminate Ck's subscription"` is blocked without `--allow-destructive`
- [ ] `bss ask "terminate Ck's subscription" --allow-destructive` succeeds
- [ ] `bss` with no args opens REPL, context persists across turns
- [ ] A deliberate policy violation ("close CASE-xxx with open tickets") is reported cleanly by the LLM with the rule ID
- [ ] LLM tool calls log structured JSON to stdout/file
- [ ] Every CLI action shows up as an interaction in the relevant customer's log
- [ ] `make cli-test`, `make orchestrator-test` pass

## Out of scope

- `bss trace` ASCII swimlane (Phase 11 — needs OTel)
- Streaming token output in REPL (nice-to-have)
- Tab completion for IDs
- Color themes
- Save/load REPL sessions

## Session prompt

> Read `CLAUDE.md`, `TOOL_SURFACE.md`, `phases/PHASE_07.md`, `phases/PHASE_08.md`, `phases/PHASE_09.md`.
>
> Before coding:
> 1. List every Typer command group and subcommand with its arguments
> 2. List every LangGraph tool and confirm it maps 1:1 to `TOOL_SURFACE.md`
> 3. Sketch each ASCII renderer as a mock-up (paste in DECISIONS.md)
> 4. Paste the full system prompt including few-shot examples
>
> Wait for approval. Implement in this order:
> 1. Direct Typer commands (without LLM) — verify end-to-end flows work via CLI
> 2. ASCII renderers — subscription first (hero), then the rest
> 3. LangGraph tools + supervisor
> 4. Channel injection and interaction auto-logging wire-through
> 5. REPL
> 6. Integration tests

## The discipline

**Build the direct CLI first.** If `bss customer create` doesn't work explicitly, the LLM version won't save you — it'll just obscure the bug.

**Tools stay dumb.** If you catch yourself adding retry logic to a tool, stop. That's supervisor territory.

**Don't try to make the LLM "smart".** It only needs to be good enough to chain 3-5 tool calls with clean error handling. A dumb-but-reliable orchestrator beats a clever one that fabricates IDs.
