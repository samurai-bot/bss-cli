"""Deterministic action registry.

Scenario ``action:`` fields map 1:1 onto orchestrator tools for the
common case — ``customer.create`` in YAML → ``TOOL_REGISTRY['customer.create']``.
A small number of scenario-only verbs (operational fan-outs that aren't
appropriate for the LLM tool surface) are registered here instead:

* ``admin.reset_operational_data`` — fan out to every service with a
  reset endpoint. Same code path as ``bss admin reset``.
* ``clock.freeze`` / ``clock.unfreeze`` / ``clock.advance`` — fan out to
  every clock-equipped service's ``/admin-api/v1/clock/*`` endpoint.
  Overrides the NOT_IMPLEMENTED stubs in orchestrator.tools.ops.

Unknown actions raise ``KeyError``; the runner surfaces that as a
``schema-level failure`` rather than a step failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from bss_clients import AdminClient, AuditClient, TokenAuthProvider
from bss_clients.errors import ClientError, NotFound, ServerError, Timeout
from bss_middleware import api_token
from bss_orchestrator.config import settings
from bss_orchestrator.tools import TOOL_REGISTRY

AsyncAction = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class _ServiceTarget:
    label: str
    base_url: str


# Services that own operational data (same list as `bss admin reset`).
_RESET_TARGETS: list[_ServiceTarget] = [
    _ServiceTarget("mediation", settings.mediation_url),
    _ServiceTarget("subscription", settings.subscription_url),
    _ServiceTarget("som", settings.som_url),
    _ServiceTarget("com", settings.com_url),
    _ServiceTarget("provisioning-sim", settings.provisioning_url),
    _ServiceTarget("payment", settings.payment_url),
    _ServiceTarget("crm", settings.crm_url),
]

# Services with the clock admin router mounted (see grep in Phase 10 prep).
_CLOCK_TARGETS: list[_ServiceTarget] = [
    _ServiceTarget("crm", settings.crm_url),
    _ServiceTarget("payment", settings.payment_url),
    _ServiceTarget("com", settings.com_url),
    _ServiceTarget("som", settings.som_url),
    _ServiceTarget("subscription", settings.subscription_url),
    _ServiceTarget("mediation", settings.mediation_url),
    _ServiceTarget("rating", settings.rating_url),
    _ServiceTarget("provisioning-sim", settings.provisioning_url),
    # v0.7 — catalog active-window math reads bss_clock.now() server-side.
    _ServiceTarget("catalog", settings.catalog_url),
]


# ─────────────────────────────────────────────────────────────────────────────
# Fan-out scenario-only actions
# ─────────────────────────────────────────────────────────────────────────────


async def admin_reset_operational_data(
    reset_sequences: bool = False,
) -> dict[str, Any]:
    """Call every service's ``/admin-api/v1/reset-operational-data`` endpoint.

    Returns the aggregated summary. Raises on any service failure so the
    scenario setup hard-fails — half-reset state is worse than no reset.
    """
    results: list[dict[str, Any]] = []
    auth = TokenAuthProvider(api_token())
    for target in _RESET_TARGETS:
        client = AdminClient(base_url=target.base_url, auth_provider=auth)
        try:
            body = await client.reset_operational_data()
            results.append({"service": target.label, "ok": True, "body": body})
        except (NotFound, ClientError, ServerError, Timeout) as e:
            raise RuntimeError(
                f"admin.reset_operational_data failed on {target.label}: {e}"
            ) from e
        finally:
            await client.close()
    return {"resetSequences": reset_sequences, "services": results}


async def _clock_fanout(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    per_service: list[dict[str, Any]] = []
    headers = {"X-BSS-API-Token": api_token()}
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        for target in _CLOCK_TARGETS:
            url = f"{target.base_url}/admin-api/v1{path}"
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"{target.label} {path}: {resp.status_code} {resp.text}"
                    )
                per_service.append({"service": target.label, "body": resp.json()})
            except httpx.HTTPError as e:
                raise RuntimeError(f"{target.label} {path}: {e}") from e
    return {"path": path, "payload": payload, "services": per_service}


async def clock_freeze(at: str | None = None) -> dict[str, Any]:
    """Freeze every service's scenario clock at ``at`` (ISO-8601) or now."""
    return await _clock_fanout("/clock/freeze", {"at": at} if at else {})


async def clock_unfreeze() -> dict[str, Any]:
    return await _clock_fanout("/clock/unfreeze", {})


async def clock_advance(duration: str) -> dict[str, Any]:
    """Advance every service's clock by ``duration`` (e.g. ``"30d"``, ``"1h"``)."""
    return await _clock_fanout("/clock/advance", {"duration": duration})


async def _fetch_events_by_identity(
    service_identity: str,
    *,
    aggregate_type: str | None,
    aggregate_id: str | None,
    event_type_prefix: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Inner helper — query CRM's audit-events router and return the list."""
    auth = TokenAuthProvider(api_token())
    async with AuditClient(base_url=settings.crm_url, auth_provider=auth) as ac:
        return await ac.list_events(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type_prefix=event_type_prefix,
            service_identity=service_identity,
            limit=limit,
        )


async def audit_events_by_identity(
    service_identity: str,
    *,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    event_type_prefix: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """v0.9 — return audit.domain_event rows scoped to a perimeter identity.

    ``audit.domain_event`` is a single table in the shared Postgres
    instance, so any service's ``/audit-api/v1/events`` exposes the
    full log. We hit CRM by convention (always running in compose).

    Returns the events list directly (not a wrapped dict) so
    scenario ``assert: any_match:`` can pivot on individual rows.
    Pair with ``audit.count_by_identity`` for count assertions.
    """
    return await _fetch_events_by_identity(
        service_identity,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type_prefix=event_type_prefix,
        limit=limit,
    )


async def audit_count_by_identity(
    service_identity: str,
    *,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    event_type_prefix: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Companion to ``audit.events_by_identity`` — returns ``{count, identity}``.

    Lets a scenario assert on cardinality (``count: { gte: 1 }``) without
    iterating the events list.
    """
    events = await _fetch_events_by_identity(
        service_identity,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type_prefix=event_type_prefix,
        limit=limit,
    )
    return {"identity": service_identity, "count": len(events)}


async def portal_write_demo_contact(
    customer_id: str,
    *,
    medium_type: str = "email",
    value: str = "portal-demo@bss-cli.local",
) -> dict[str, Any]:
    """v0.9 hero — perform a single write attributed to the portal identity.

    Constructs a ``NamedTokenAuthProvider("portal_self_serve",
    "BSS_PORTAL_SELF_SERVE_API_TOKEN")`` so the receiving CRM service resolves
    ``service_identity="portal_self_serve"`` from token validation. The
    write itself is a contact-medium add — a small, auditable mutation
    that fires a single ``customer.contact_medium_added`` event.

    The TMF body shape (`{mediumType, value}`) is sent as a direct
    httpx POST rather than via ``CRMClient.add_contact_medium`` because
    the existing client method wraps ``value`` inside a TMF
    ``characteristic`` block that the v0.1 CRM endpoint does not
    accept. Fixing the client is pre-v0.9 scope-creep; the scenario
    sidesteps it.

    Required env: ``BSS_PORTAL_SELF_SERVE_API_TOKEN`` must be set AND must be present
    in the BSS services' TokenMap (i.e., the same value the services
    loaded at startup). Without that, the perimeter middleware 401s.
    No fallback to BSS_API_TOKEN here — the hero scenario's whole point
    is to demonstrate the distinct identity, so the action fails loud
    when the named token isn't provisioned. ``NamedTokenAuthProvider``
    raises ``RuntimeError("BSS_PORTAL_SELF_SERVE_API_TOKEN is unset")`` directly
    when the env is missing, which surfaces in the scenario report.
    """
    from bss_clients import NamedTokenAuthProvider

    auth = NamedTokenAuthProvider(
        "portal_self_serve",
        "BSS_PORTAL_SELF_SERVE_API_TOKEN",
        # No fallback — see docstring: failing loud is the point.
        fallback_env_var=None,
    )
    headers = await auth.get_headers()
    url = (
        f"{settings.crm_url}/tmf-api/customerManagement/v4/customer/"
        f"{customer_id}/contactMedium"
    )
    body = {"mediumType": medium_type, "value": value}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"portal-token contactMedium add failed: "
                f"{resp.status_code} {resp.text}"
            )
        result = resp.json()
    return {
        "identity": auth.identity,
        "customerId": customer_id,
        "result": result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

# Scenario-only overrides. These SHADOW any same-named TOOL_REGISTRY entry
# (e.g. orchestrator.tools.ops.clock_freeze is a NOT_IMPLEMENTED stub —
# scenarios need the real fan-out).
_SCENARIO_ACTIONS: dict[str, AsyncAction] = {
    "admin.reset_operational_data": admin_reset_operational_data,
    "clock.freeze": clock_freeze,
    "clock.unfreeze": clock_unfreeze,
    "clock.advance": clock_advance,
    # v0.9 — perimeter-identity audit query for hero scenario assertions.
    # Not exposed as an LLM tool (the LLM has trace.for_order / trace.for_subscription
    # for trace-level lookups). Operator-shaped audit pivots stay in scenario land.
    "audit.events_by_identity": audit_events_by_identity,
    "audit.count_by_identity": audit_count_by_identity,
    # v0.9 — used by the named-token hero scenario to make a write that
    # carries BSS_PORTAL_SELF_SERVE_API_TOKEN, demonstrating the distinct audit
    # attribution (service_identity="portal_self_serve").
    "portal.write_demo_contact": portal_write_demo_contact,
}


def resolve_action(name: str) -> AsyncAction:
    """Return the callable for ``name`` — scenario override first, then tools."""
    if name in _SCENARIO_ACTIONS:
        return _SCENARIO_ACTIONS[name]
    if name in TOOL_REGISTRY:
        return TOOL_REGISTRY[name]
    raise KeyError(f"unknown action: {name!r}")


def action_names() -> list[str]:
    """All registry entries — scenario overrides + tool registry."""
    return sorted(set(_SCENARIO_ACTIONS) | set(TOOL_REGISTRY))
