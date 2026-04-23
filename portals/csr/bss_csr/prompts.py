"""Natural-language prompt template for CSR-driven agent flows.

The prompt the LLM sees is the operator's question plus a snapshot of
the customer's current state. Without the snapshot, a small model
burns tool calls rediscovering what the operator already sees on
screen — *"who is this customer, what plan are they on, are they
blocked?"*. With it, the agent lands on the right subtree
immediately (``subscription.get_balance`` for data questions,
``case.list`` for ticket questions, etc.).

KNOWN_LEADS gives few-shot examples for the three most common ask
patterns so MiMo v2 Flash stays on rails.
"""

from __future__ import annotations

from typing import Any


KNOWN_LEADS: list[dict[str, str]] = [
    {
        "question": "Why is their data not working? Fix it if you can.",
        "lead": (
            "Likely a blocked subscription (bundle exhausted). Confirm with "
            "subscription.get; if blocked, list available VAS top-ups via "
            "catalog.list_vas and purchase one with subscription.purchase_vas. "
            "Log a short interaction note via interaction.log when done."
        ),
    },
    {
        "question": "Top up 5GB to their plan.",
        "lead": (
            "Find a 5GB VAS offering via catalog.list_vas, then call "
            "subscription.purchase_vas on the customer's active subscription. "
            "Log an interaction note summarising the top-up."
        ),
    },
    {
        "question": "Open a technical ticket about the missed renewal.",
        "lead": (
            "Use case.open with category='technical' and a clear subject; "
            "ticket.add to attach a child ticket; log via interaction.log."
        ),
    },
]


def build_csr_prompt(
    *,
    operator_id: str,
    customer_id: str,
    question: str,
    customer_snapshot: dict[str, Any],
    subscription_snapshot: list[dict[str, Any]],
) -> str:
    """Compose the NL prompt the agent sees.

    Snapshot fields are pre-fetched by ``agent_bridge.ask_about_customer``
    so the agent doesn't waste a turn re-reading the same state from
    services.
    """
    leads = "\n".join(
        f'  Q: "{lead["question"]}"\n  Plan: {lead["lead"]}'
        for lead in KNOWN_LEADS
    )

    sub_lines = (
        "\n".join(
            f"  - {s['id']} | state={s['state']} | offering={s['offering']}"
            for s in subscription_snapshot
        )
        if subscription_snapshot
        else "  (no subscriptions on file)"
    )

    return (
        f"You are a CSR assistant. Operator '{operator_id}' is looking at "
        f"customer {customer_id} and asks:\n\n"
        f"  > {question}\n\n"
        f"Current state of {customer_id}:\n"
        f"  name: {customer_snapshot.get('name', '?')}\n"
        f"  email: {customer_snapshot.get('email', '?')}\n"
        f"  status: {customer_snapshot.get('status', '?')}\n"
        f"  kyc: {customer_snapshot.get('kyc_status', '?')}\n"
        f"\n"
        f"Subscriptions:\n{sub_lines}\n"
        f"\n"
        f"Common patterns and the recommended tool chains:\n{leads}\n"
        f"\n"
        f"Constraints:\n"
        f"  - Do not call destructive tools (subscription.terminate, "
        f"customer.close, ticket.cancel, payment.remove_method, order.cancel).\n"
        f"  - Always end by logging a short interaction note via "
        f"interaction.log so the next CSR has context.\n"
        f"  - Report briefly what you did and the resulting state."
    )
