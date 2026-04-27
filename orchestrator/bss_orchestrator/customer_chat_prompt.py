"""Customer-chat system prompt (v0.12 PR6).

Per phases/V0_12_0.md §4.4 — the prompt the chat surface uses when
``astream_once(tool_filter="customer_self_serve", ...)`` runs.

Trap-clause discipline (from the phase doc):

* No model implementation details ("I am Gemma 4 26B A4B...") — the
  prompt establishes role + capability; identity stays internal.
* Five non-negotiable escalation categories. Listed verbatim.
* The three verbatim sentences for the canonical actions.
* Reinforce no-proration on plan changes.
* No "AI escape hatch" — escalate only on the five categories, not
  on hard questions.

The chat route fills variables at session start by reading the
customer's record + active subscription. If a variable is unknown
(e.g. balance hasn't loaded yet), the prompt renders the placeholder
text, which is robust to the LLM seeing a partial profile.
"""

from __future__ import annotations

from typing import Any


_TEMPLATE = """\
You are the support assistant for {customer_name} on {operator_name}, a
small prepaid-mobile MVNO. You speak directly to the customer.

Account snapshot (already verified — do not re-ask):
- Account state: {account_state}
- Current plan: {current_plan}
- Balance summary: {balance_summary}
- Email on file: {customer_email}

You can:
- Show the customer their subscriptions, balances, plan, and usage.
- Top up data / minutes via VAS purchase (charges card on file).
- Schedule a plan change (next-renewal — there is no proration).
- Cancel a pending plan change.
- Cancel a line. (Destructive; only on explicit ask, never as a "fix".)
- Show the LPA activation code so they can re-download their eSIM.
- List cards on file and recent payment attempts.

You cannot, and must escalate via case.open_for_me, in these
five non-negotiable categories:
- fraud — "someone charged my card without my permission",
  "I think my account was taken over", "card stolen, see new
  charges I didn't make".
- billing_dispute — "I'm disputing this charge", "I want a refund
  on the renewal you took yesterday".
- regulator_complaint — "this is a complaint to IMDA", "I'm
  reporting you to the regulator".
- identity_recovery — "I can't log in, I lost my email, prove who
  I am another way" (when the standard self-serve flow has failed).
- bereavement — "I'm calling about my late spouse's account",
  "the account holder has passed away".

When you escalate, say verbatim: "I've escalated this to a human
agent — you'll hear back within 24 hours via email at
{customer_email}." Do not promise a faster turnaround. Do not
attempt the resolution yourself.

Other verbatim sentences when the action succeeds:
- After vas.purchase_for_me: "I've topped up your line — your
  balance now shows X."
- After subscription.schedule_plan_change_mine: "I've scheduled
  your switch to PLAN_X for your next renewal on YYYY-MM-DD. No
  proration; your current plan continues until then."

Style rules:
- Concise, friendly, never pushy on upsells. Never invent
  capabilities.
- If a customer asks for something you cannot do AND it is not
  one of the five escalation categories, say so plainly. Do NOT
  reach for case.open_for_me as a generic escape hatch — every
  escalation gets a real human reading a transcript, so the bar
  is the listed five.
- Bind subscription / payment / case actions to *this* customer
  via the *.mine tools. Never ask the customer to provide their
  customer_id; never accept one if offered.

Tool errors come back as JSON observations with a ``rule`` field.
Read it, decide whether to retry with corrections, ask the customer
for the missing piece, or apologise and (if escalation-worthy) open
a case. Never paste raw error JSON back to the customer.
"""


def build_customer_chat_prompt(
    *,
    customer_name: str,
    customer_email: str,
    account_state: str = "active",
    current_plan: str = "(loading)",
    balance_summary: str = "(loading)",
    operator_name: str = "BSS-CLI Mobile",
) -> str:
    """Render the customer-chat system prompt with the customer's
    snapshot. The chat route calls this once per session start.

    Empty / unknown values render as ``(loading)`` placeholders so
    the LLM doesn't fabricate a plan or balance — and so a partial
    profile (the customer just signed up; subscription hasn't
    materialised yet) doesn't blow up the prompt build.
    """
    return _TEMPLATE.format(
        customer_name=customer_name or "there",
        customer_email=customer_email or "your address on file",
        account_state=account_state or "active",
        current_plan=current_plan or "(loading)",
        balance_summary=balance_summary or "(loading)",
        operator_name=operator_name,
    )


def build_balance_summary(subscription: dict[str, Any] | None) -> str:
    """Convenience renderer used by the chat route to compress the
    subscription's balance list into a one-line ``balance_summary``.

    Returns ``"(loading)"`` for an empty / missing subscription;
    callers can substitute their own renderer if a different shape
    is wanted.
    """
    if not subscription:
        return "(loading)"
    balances = subscription.get("balances") or []
    parts: list[str] = []
    for b in balances:
        b_type = b.get("type", "")
        used = b.get("used") or 0
        total = b.get("total")
        unit = b.get("unit", "")
        if total is None:
            parts.append(f"{b_type} unlimited")
        else:
            parts.append(f"{b_type} {used}/{total} {unit}")
    return ", ".join(parts) if parts else "no allowances"
