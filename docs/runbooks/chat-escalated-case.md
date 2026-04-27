# Reviewing an escalated chat case

When the customer chat surface escalates a conversation via
`case.open_for_me`, a CRM case lands with a non-null
`chat_transcript_hash`. CSRs review these via the v0.5 console's
case-detail page (with the v0.12 transcript panel) and decide
whether to action, transfer, or close.

## Identify chat-escalated cases

```sql
SELECT id, customer_id, subject, category, priority, opened_at,
       chat_transcript_hash
FROM crm.case
WHERE chat_transcript_hash IS NOT NULL
  AND state = 'open'
ORDER BY opened_at DESC;
```

The subject + first paragraph of `description` (which is `[<category>] <free text>`)
gives the operator a triage hint without opening the page.

## Open the case in CSR console

Navigate to `/case/{case_id}`. The v0.12 page renders:

* The case header (subject, state, priority, category — these
  carry the `EscalationCategory` to CRM-CaseCategory mapping
  from `mine_wrappers._ESCALATION_TO_CASE_CATEGORY`).
* Tickets (none expected; AI-opened cases don't auto-spawn
  tickets in v0.12).
* Notes (empty initially; CSR adds notes during triage).
* **Chat transcript** — the v0.12 panel. Renders the conversation
  body verbatim; preserves the `User: ... / Assistant: ...`
  format the orchestrator stored.

If the transcript panel says "no longer retrievable", the
transcript was archived per the retention rules — see the
chat-transcript-retention runbook.

## Triage decisions per category

* **fraud** — verify with the customer via a confirmed contact
  channel before any account action. If confirmed, walk through
  the standard fraud playbook (lock COF, flag account, escalate
  to fraud team). The case is the audit trail.
* **billing_dispute** — read the transcript to understand which
  charge the customer is disputing; pull the matching
  `payment.payment_attempt` row + the `audit.domain_event` for
  that attempt. Decide refund vs explain.
* **regulator_complaint** — escalate to the compliance contact
  immediately; do not engage on substance from the chat. The
  case + transcript are the regulatory evidence.
* **identity_recovery** — the customer is locked out of the
  standard self-serve flow; identity verification happens via a
  channel the AI cannot drive (in-person, video call). The case
  routes to that team.
* **bereavement** — the existing bereavement process; close the
  customer's lines per the family's request after appropriate
  documentation. The case is the trigger; do not let the AI
  attempt anything here.
* **other** — re-categorise on review. If it actually fits one
  of the five, update the case category. If it's nothing-burger
  (the AI escalated something it shouldn't have), close
  resolution_code=`prompt_drift` and add the prompt to the soak
  corpus's NOT-an-escalation list to retrain the prompt.

## Record the resolution

```python
case.add_note(case_id, body="...", author_agent_id="<op>")
case.close(case_id, resolution_code="<code>")
```

Standard resolution codes: `resolved_in_chat` (false escalation),
`fraud_confirmed`, `dispute_refunded`, `dispute_explained`,
`regulator_handled`, `identity_recovered`, `bereavement_closed`.

## Adversarial transcripts

If a transcript looks like a prompt-injection attempt (the user
wrote "ignore previous instructions and..."), check whether the
agent actually escalated for the wrong reason. The wrappers +
trip-wire should have stopped any cross-customer action; the
case is the visible artifact of "AI saw something fishy and
asked a human." Close `resolution_code=prompt_injection_blocked`
and add the prompt verbatim to the soak's
`CROSS_CUSTOMER_PROBES` corpus so the next soak run regression-
tests it.
