# Adding a tool to the `customer_self_serve` profile

> **The profile is curated, not generated.** Every entry widens
> the chat surface's autonomous reach. The narrowness is a
> feature: a leaked credential or a prompt-injection attempt can
> only reach what's in the profile. Adding a tool is a security
> review.

## Pre-flight checklist

Before starting the implementation, answer these in order. If
any answer is "no" or "uncertain", stop and discuss with the team
instead of writing the wrapper.

* [ ] **Is there a customer-direct UI route for the same action?**
  If a customer can already do this from the dashboard / billing
  / payment-methods pages, the chat tool is a convenience layer
  on top. If not, you're widening the surface beyond direct UI —
  that's a doctrine question, not a security checklist item.

* [ ] **Is the action ownership-bound?** The wrapper must be able
  to derive everything it needs from `auth_context.current().actor`
  + a non-customer-bound parameter (subscription_id, vas_offering_id,
  etc.). Tools that need a `customer_id` argument by definition
  cannot be `*.mine`-shaped.

* [ ] **Does the canonical tool's server-side policy enforce
  ownership?** The wrapper's pre-check produces the friendly
  error message; the policy is the actual gate. If the canonical
  tool relies on the caller passing the right `customer_id`
  (an unscoped read), add the policy server-side BEFORE adding
  the wrapper.

* [ ] **Is the response shape stable enough to register an
  `OWNERSHIP_PATHS` entry?** If the canonical tool returns a
  union type or a polymorphic dict, the trip-wire's path-walker
  may not find the customer-bound field reliably. Stabilise the
  contract first.

* [ ] **Does the tool have an audit story?** Every chat-driven
  action should be discoverable from the customer's interaction
  log. The CRM auto-logging covers most write paths; reads with
  no side effects are exempt.

## Implementation steps

1. **Wrapper** in `orchestrator/bss_orchestrator/tools/mine_wrappers.py`:

   ```python
   @register("<namespace>.<action>_mine")  # or _for_me for one-shot writes
   async def <namespace>_<action>_mine(
       <only-non-owner-bound-params>: ...,
   ) -> dict[str, Any]:
       """One-line summary.

       Args:
           ...

       Returns:
           ...

       Raises:
           policy.<...>.not_owned_by_actor: ...
           chat.no_actor_bound: invoked outside a chat-scoped session.
       """
       actor = _require_actor()
       # Pre-check ownership where applicable:
       await _assert_subscription_owned(subscription_id, actor)
       return await get_clients().<service>.<canonical>(...)
   ```

   No `customer_id` parameter. The startup self-check
   (`tools/_profiles.validate_profiles`) refuses to boot if you
   slip one in.

2. **Profile entry** in
   `orchestrator/bss_orchestrator/tools/_profiles.py`:

   Add the new tool name to `TOOL_PROFILES["customer_self_serve"]`.
   Comment with a one-line rationale ("for customers who ask
   '<canonical user phrasing>'").

3. **Ownership-paths entry** in
   `orchestrator/bss_orchestrator/ownership.py`:

   Add the tool name to `OWNERSHIP_PATHS`. Use `[]` only when the
   tool's response carries no customer-bound fields by contract
   (rare). The startup self-check refuses missing entries.

4. **TOOL_SURFACE.md row.** Add a row to the customer-scoped
   wrappers table; the registry-doc consistency test enforces.

5. **System prompt update** in
   `orchestrator/bss_orchestrator/customer_chat_prompt.py`:

   Add the new capability to the "You can:" list. Be concrete
   ("show me my last password reset" not "do password things").
   If the tool produces a response the customer should hear
   verbatim (e.g., "I've topped up your line"), add a verbatim
   sentence pin.

6. **Soak corpus update** in
   `scenarios/soak/corpus.py`:

   Add 1-3 normal asks that should trigger this tool. The soak
   exercises the new path under load.

7. **Tests:**
   - Unit test in `orchestrator/tests/test_tool_profiles.py`:
     * `test_<tool>_blocks_cross_customer` (cross-customer
       subscription_id rejected via the wrapper's pre-check).
     * `test_<tool>_passes_through_when_owned`.
   - Trip-wire test in `orchestrator/tests/test_ownership_check.py`:
     * Planted bad payload with the new tool's path trips.
   - If the tool is destructive, add it to `safety.DESTRUCTIVE_TOOLS`
     and assert membership in a test.

8. **Hero scenario refresh.** The chat hero scenarios in
   `scenarios/portal_chat_*.yaml` should exercise the new tool
   on the happy path.

## Post-deploy checks

* `make test` green — including the new tests.
* `make doctrine-check` green — the `astream_once` whitelist is
  unchanged; the wrapper's signature inspection passes.
* `make scenarios-hero` 3-runs-green — the chat heroes still
  pass with the new tool reachable.
* On the live stack: tail the orchestrator's structlog while the
  test customer asks the canonical question. Confirm the new
  tool fires + the response renders cleanly + no trip-wire alarm.

## When to remove a tool

Profiles should shrink, not just grow. If a tool the chat
exposes turns out to be unused or doctrine-violating, remove
the entry from `TOOL_PROFILES` + the corresponding
`OWNERSHIP_PATHS` entry + the TOOL_SURFACE.md row. The wrapper
itself stays registered so the canonical chain still works for
any pre-existing references; it just isn't exposed to the chat
surface.
