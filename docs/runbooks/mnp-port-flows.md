# MNP — port-in / port-out flows

> v0.17. Operator-driven by spec. No customer self-serve path.

The two flows hang off the `crm.port_request` aggregate. FSM:
`requested → validated → completed | rejected`. v0.17 ships only
the operator-driven `requested → completed | rejected` path;
`validated` is a hook for a future automated donor-carrier check.

## Surfaces

- **REPL** — `bss` then `/ports`:
  - `/ports` or `/ports list` — Rich-table list (state, direction, donor MSISDN, carrier, target sub, requested port date)
  - `/ports approve PORT-NNN`
  - `/ports reject PORT-NNN <reason>`
- **Cockpit (browser)** — drive via chat. Tools registered:
  `port_request.list`, `port_request.get`, `port_request.create`,
  `port_request.approve`, `port_request.reject`. The agent proposes
  destructive actions (approve / reject) — operator confirms via the
  Confirm button (or `/confirm` in REPL twin) before they execute.
- **HTTP** — `/crm-api/v1/port-requests` on the CRM service (port 8002).

## Port-in (customer brings number to us)

Customer arrives wanting to bring `91005555` from carrier "ACME Mobile".

1. **Open the request:**
   ```
   > open a port-in for donor MSISDN 91005555 from carrier "ACME Mobile",
     requested port date 2026-05-25
   ```
   Agent calls `port_request.create(direction=port_in, donor_carrier=..., donor_msisdn=..., requested_port_date=...)`.
   Returns `PORT-NNNN` in state `requested`.

2. **(Optional) link a target subscription.** If the customer has already
   signed up and you want the donor MSISDN auto-assigned at approve time,
   pass `target_subscription_id=SUB-XXXX` at create. If you don't, the
   donor MSISDN gets seeded into the pool as `available` and a normal
   signup will reserve it.

3. **Approve.** Operator types `/ports approve PORT-NNNN` (REPL) or asks
   the agent to approve and confirms. The approve handler:
   - Inserts the donor MSISDN into `inventory.msisdn_pool` with
     `ON CONFLICT (msisdn) DO NOTHING` — if a previous port-in already
     seeded it, the prior row wins (no error, just a no-op).
   - Status becomes `assigned` (if `target_subscription_id` was set) or
     `available` (otherwise).
   - Emits `inventory.msisdn.seeded_from_port_in`, `port_request.approved`,
     `port_request.completed`.

4. **Verify.** `bss inventory msisdn show 91005555` — should show the
   number with the right status.

## Port-out (customer takes number to a competitor)

Customer wants to take MSISDN `90000007` (currently on `SUB-1234`) to
another carrier.

1. **Open the request.** `target_subscription_id` is **required** for
   port-out (the policy `port_request.create.target_sub_required_for_port_out`
   enforces this):
   ```
   > open a port-out for SUB-1234, donor carrier "BSS-CLI",
     requested port date 2026-05-25
   ```

2. **Approve.** The approve handler:
   - Flips `inventory.msisdn_pool.status` for the donor MSISDN to
     terminal `ported_out` with `quarantine_until='9999-12-31'`. The
     reserve-next predicate is `status='available'` so the number is
     skipped by construction forever after.
   - Emits `inventory.msisdn.ported_out`.
   - Calls `SubscriptionClient.terminate(target_subscription_id, reason='ported_out', release_inventory=False)`.
     The new v0.17 `release_inventory=False` kwarg is critical here —
     terminate's default path releases the MSISDN back to `available`,
     which would undo the `ported_out` flip in the same transaction.
     Subscription transitions to `terminated`; eSIM still recycles.
   - Emits `port_request.approved`, `port_request.completed`,
     `subscription.terminated` (with reason `ported_out`).

3. **Verify.** `bss inventory msisdn show 90000007` should show
   `status=ported_out`. `bss subscription show SUB-1234` should show
   `state=terminated`.

## Rejecting a request

```
> /ports reject PORT-NNNN donor carrier denied
```

Reason is required (policy `port_request.reject.requires_reason`).
Emits `port_request.rejected`. State is terminal — a re-port of the
same donor MSISDN can be opened later without conflict (the unique
index on `donor_msisdn` is partial WHERE state in `(requested, validated)`).

## Doctrine reminders (CLAUDE.md v0.17+)

- Don't overload `Case` for port requests. `crm.port_request` is its own
  aggregate.
- Don't release a `ported_out` MSISDN back to `available`. It's terminal.
  Greppable: `rg "ported_out.*'available'|'available'.*ported_out" services/crm/app/repositories/msisdn_repo.py` must stay empty.
- Don't expose port-request writes to `customer_self_serve`. MNP is
  operator-driven by spec. `validate_profiles()` self-checks at startup.

## Limits (intentional)

- No automated donor-carrier validation. Operator is the validator
  in v0.17.
- No inbound port pre-validation flow ("is my number portable?") for
  the customer. Channel-layer concern, same posture as eKYC.
- No SM-DP+ rearm for ported-out subscribers. Port-out terminates
  the subscription; the GSMA SGP.22 rearm flow remains a post-v0.1
  SOM task as documented in CLAUDE.md.

## See also

- `phases/V0_17_0.md` — full v0.17 phase notes.
- `DECISIONS.md` — three v0.17 entries (port_request as own aggregate,
  data_roaming as additive bucket, roaming_indicator on UsageEvent).
- Hero scenarios:
  - `scenarios/operator_port_in_seeds_pool.yaml`
  - `scenarios/operator_port_out_terminates_subscription.yaml`
