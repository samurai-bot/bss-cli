"""v0.18 — automated subscription-renewal worker.

In-process tick loop attached to the subscription service's lifespan
(`app.dependencies.lifespan`). The worker is the ONLY place that
triggers renewals automatically; the manual paths
(`subscription.renew_now` cockpit tool, `bss subscription renew` CLI,
scenario action) remain as operator escape hatches.

Doctrine (CLAUDE.md v0.18+):
- Worker calls ``SubscriptionService.renew(sub_id)`` and nothing else.
  No re-implementation of charge logic, no parallel state machine.
- Trigger lives only in this module + the lifespan that starts it.
  Greppable: `_renewal_tick_loop` / `_sweep_due` / `_sweep_skipped`
  must not appear in any other production code path.

Correctness invariants:

1. **Mark-before-dispatch.** The SELECT-FOR-UPDATE-SKIP-LOCKED batch
   commits the `last_renewal_attempted_at` write BEFORE releasing the
   row locks. A peer replica running its own sweep at the same moment
   sees the marked dedup column the instant the lock is gone, so it
   skips the row. Without this ordering, two replicas can each grab a
   batch, both write the mark, both proceed to charge — double billing.

2. **Per-id session for dispatch.** Each `renew()` call runs in its own
   `async with session_factory()` so a single subscription's failure
   does NOT poison the rest of the batch. Errors per id log and
   continue.

3. **ContextVar reset in finally.** The publisher reads
   `actor`/`channel`/`service_identity` from `auth_context._current`,
   which is per-asyncio-Task. The worker is one long-lived Task, so
   values would leak across iterations. `auth_context.push()` returns
   a Token; `pop(token)` in `finally` resets.

4. **Cancellation semantics.** The outer loop catches
   `asyncio.CancelledError` to log the shutdown signal and re-raise.
   In-flight `renew()` calls are NOT shielded — they roll back via
   their `async with session_factory()` and the next process picks
   them up because `last_renewal_attempted_at` was committed by the
   (already-flushed) SELECT-txn.

5. **Wall-clock interval, bss_clock WHERE.** `asyncio.sleep(interval)`
   uses real wall-clock time so the loop's cadence is the operator
   contract (`BSS_RENEWAL_TICK_SECONDS`). The WHERE clause uses
   `bss_clock.now()` so frozen-clock scenarios drive the worker
   deterministically.
"""

from __future__ import annotations

import asyncio

import structlog
from bss_clock import now as clock_now

from app import auth_context
from app.events import publisher
from app.policies.base import PolicyViolation
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.vas_repo import VasPurchaseRepository
from app.services.subscription_service import SubscriptionService

log = structlog.get_logger()

_BATCH_LIMIT = 100
_WORKER_ACTOR = "system:renewal_worker"
_WORKER_CHANNEL = "system"


async def _renewal_tick_loop(app, interval_seconds: int) -> None:
    """Forever loop. Sweep due + skipped, sleep interval, repeat.

    Crashes inside a sweep are logged and swallowed — the loop survives
    a transient DB blip without taking down the lifespan task. Only
    `asyncio.CancelledError` exits the loop (clean shutdown).
    """
    log.info(
        "renewal.worker.started",
        interval_seconds=interval_seconds,
        batch_limit=_BATCH_LIMIT,
    )
    try:
        while True:
            try:
                await _sweep_due(app)
                await _sweep_skipped(app)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("renewal.worker.sweep_crashed")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("renewal.worker.cancelled")
        raise


async def _sweep_due(app) -> None:
    """Find active+due subs, mark each, dispatch renew() per id.

    Two transactions per sweep:
    1. SELECT FOR UPDATE SKIP LOCKED + bulk UPDATE mark + commit.
    2. Per-id: open fresh session, set worker auth context, call
       `service.renew(id)`, swallow per-id failures.
    """
    now = clock_now()

    # ── Txn 1: select + mark + commit ─────────────────────────────────
    async with app.state.session_factory() as session:
        repo = SubscriptionRepository(session)
        ids = await repo.due_for_renewal(now=now, limit=_BATCH_LIMIT)
        if not ids:
            return
        await repo.mark_renewal_attempted(ids=ids, at=now)
        await session.commit()

    # ── Txn 2 (one per id): dispatch via the canonical service.renew ──
    for sub_id in ids:
        token = auth_context.push(
            actor=_WORKER_ACTOR,
            channel=_WORKER_CHANNEL,
        )
        try:
            async with app.state.session_factory() as session:
                svc = SubscriptionService(
                    session=session,
                    repo=SubscriptionRepository(session),
                    vas_repo=VasPurchaseRepository(session),
                    crm_client=app.state.crm_client,
                    payment_client=app.state.payment_client,
                    catalog_client=app.state.catalog_client,
                    inventory_client=app.state.inventory_client,
                )
                await svc.renew(sub_id)
                log.info(
                    "renewal.worker.dispatched",
                    subscription_id=sub_id,
                )
        except PolicyViolation as exc:
            log.warning(
                "renewal.worker.policy_violation",
                subscription_id=sub_id,
                rule=exc.rule,
                message=exc.message,
            )
        except Exception:
            log.exception(
                "renewal.worker.dispatch_failed",
                subscription_id=sub_id,
            )
        finally:
            auth_context.pop(token)


async def _sweep_skipped(app) -> None:
    """Find blocked+overdue subs, emit `subscription.renewal_skipped`, mark.

    No `renew()` call — blocked subs need an explicit operator
    intervention (top-up, payment-method update). The skipped event is
    a cheap signal for the cockpit dashboard so an operator can nudge
    the customer; it is NOT a retry trigger.

    Single transaction per sweep: emit all events + bulk mark + commit.
    """
    now = clock_now()
    token = auth_context.push(
        actor=_WORKER_ACTOR,
        channel=_WORKER_CHANNEL,
    )
    try:
        async with app.state.session_factory() as session:
            repo = SubscriptionRepository(session)
            ids = await repo.overdue_blocked(now=now, limit=_BATCH_LIMIT)
            if not ids:
                return
            for sub_id in ids:
                await publisher.publish(
                    session,
                    event_type="subscription.renewal_skipped",
                    aggregate_type="subscription",
                    aggregate_id=sub_id,
                    payload={
                        "subscriptionId": sub_id,
                        "reason": "blocked",
                        "skippedAt": now.isoformat(),
                    },
                    exchange=app.state.mq_exchange,
                )
            await repo.mark_renewal_attempted(ids=ids, at=now)
            await session.commit()
            log.info(
                "renewal.worker.skipped_emitted",
                count=len(ids),
            )
    finally:
        auth_context.pop(token)
