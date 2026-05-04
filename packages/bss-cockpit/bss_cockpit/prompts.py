"""Cockpit system-prompt builder.

Composes the per-turn system prompt the operator's REPL + browser
veneer pass to ``astream_once(system_prompt=...)``. Three blocks:

1. The operator's persona + house rules (``OPERATOR.md``), prepended
   verbatim. The operator's editable contract with the agent.
2. The cockpit's invariant guidance (propose-then-confirm for
   destructive, /confirm contract). Code-defined; not editable.
3. Per-turn context blocks: ``customer_focus`` (when pinned) and the
   pending-destructive proposal payload (when the upcoming turn is
   running with ``allow_destructive=True``).

The split is doctrine: house rules are operator-customisable; the
cockpit's safety contract is code-defined. An operator who wants to
weaken the contract has to edit code, not a markdown file.

Per phases/V0_13_0.md "The trap" — OPERATOR.md drift into prompt-
injection territory is a foot-gun the operator is choosing to set
themselves; the doctrine docs surface that explicitly. This module
does not try to sanitize the markdown.
"""

from __future__ import annotations

from typing import Any

from .conversation import PendingDestructive

_COCKPIT_INVARIANTS = """\
## Cockpit safety contract (code-defined)

- Destructive tool calls (terminate, remove, cancel, refund, etc.)
  must be PROPOSED first with a one-line summary and the exact tool
  name + arguments. Wait for the operator to type `/confirm` before
  the call runs. Never call a destructive tool directly without a
  prior /confirm pairing.
- The five escalation categories — fraud, billing_dispute,
  regulator_complaint, identity_recovery, bereavement — are operator-
  side too: open a case, do not auto-resolve from the cockpit.
- Customer-bound writes still flow through the policy layer. If a
  policy violation comes back, surface it; do not retry blindly.
- ASCII tables and inline summaries are the visualisation language.
  Do not reach for markdown ornament beyond what `OPERATOR.md`
  authorizes.
- (v0.19) NEVER fabricate catalog data — plan ids, plan names,
  prices, VAS ids, VAS names, allowance quantities, allowance
  units. The catalog is the source of truth. If the operator asks
  "what plans are there", "list all products", "show me VAS
  offerings", or any similar question that requires factual catalog
  data, you MUST call one of:
    - `catalog.list_active_offerings` for plans
    - `catalog.list_vas` for VAS top-ups
    - `catalog.get_offering` for a single plan card
  THEN render the tool's return value. Do not summarize from prior
  conversation context, do not guess prices, do not fill in plan
  names from training data. The post-processor will render the
  list-shaped tool result as an ASCII table; you do not need to
  re-format it. If the operator's question is ambiguous, call the
  tool with the broadest scope and let the operator narrow the
  follow-up. A single hallucinated price is a customer-facing
  trust-loss event the platform's audit log cannot recover from.
"""


def build_cockpit_prompt(
    *,
    operator_md: str,
    customer_focus: str | None = None,
    pending_destructive: PendingDestructive | None = None,
    extra_context: dict[str, Any] | None = None,
) -> str:
    """Compose the system prompt for one cockpit turn.

    ``operator_md`` is the verbatim contents of ``OPERATOR.md`` —
    the loader has already trimmed nothing; pass it through.
    ``customer_focus`` is the pinned ``CUST-NNN`` from
    ``Conversation.customer_focus`` (or ``None``).
    ``pending_destructive`` is the *just-consumed* propose row when
    the current turn is running with ``allow_destructive=True``;
    surfaces the propose payload back to the LLM so it can confirm
    its own intent before invoking.
    ``extra_context`` is a free-form dict for future PRs (e.g.
    "current model", "session id"); rendered as a "## Context"
    block of `key: value` lines.
    """
    parts: list[str] = []

    md = (operator_md or "").rstrip()
    if md:
        parts.append(md)

    parts.append(_COCKPIT_INVARIANTS.rstrip())

    if customer_focus:
        parts.append(
            f"## Customer focus\n\nThe operator has pinned "
            f"`{customer_focus}` for this session. Default to that "
            f"customer when a question is ambiguous; ask the operator "
            f"if you need to act on a different customer."
        )

    if pending_destructive is not None:
        # Render the args as a compact `k=v` list rather than JSON
        # so the prompt stays prose-shaped.
        args_pairs = ", ".join(
            f"{k}={v!r}" for k, v in pending_destructive.tool_args.items()
        )
        parts.append(
            "## Confirmed destructive action\n\n"
            "The operator typed `/confirm` for the prior propose. "
            "You are now authorised to call exactly:\n\n"
            f"- tool: `{pending_destructive.tool_name}`\n"
            f"- args: {args_pairs or '(no args)'}\n\n"
            "Run it. Surface the result. Do not call any other "
            "destructive tool on this turn."
        )

    if extra_context:
        ctx_lines = "\n".join(
            f"- {k}: {v}" for k, v in sorted(extra_context.items())
        )
        parts.append(f"## Context\n\n{ctx_lines}")

    # Single blank line between blocks. Trailing newline keeps prompts
    # comparable in tests.
    return "\n\n".join(parts) + "\n"
