"""Order renderer — order header + SOM decomposition tree."""

from __future__ import annotations

from typing import Any

from ._box import box


def render_order(
    order: dict[str, Any],
    *,
    service_orders: list[dict[str, Any]] | None = None,
    services_by_so: dict[str, list[dict[str, Any]]] | None = None,
    tasks_by_service: dict[str, list[dict[str, Any]]] | None = None,
    subscription_id: str | None = None,
) -> str:
    """Render a product order with SOM decomposition.

    ``services_by_so`` maps service order id → list of service dicts
    (mix of CFS + RFS). ``tasks_by_service`` maps service id → list of
    provisioning tasks. Any missing pieces just render as collapsed nodes.
    """
    oid = order.get("id", "ORD-???")
    state = order.get("state", "?")
    cust_id = order.get("customerId", "—")
    items = order.get("items") or []
    offering = items[0].get("offeringId", "—") if items else "—"
    placed = order.get("orderDate", "—")
    completed = order.get("completedDate", "—")

    lines = [
        f"Customer: {cust_id}",
        f"Placed:   {placed}",
        f"Done:     {completed}",
        "",
    ]

    service_orders = service_orders or []
    services_by_so = services_by_so or {}
    tasks_by_service = tasks_by_service or {}

    for so in service_orders:
        so_id = so.get("id", "SO-???")
        so_state = so.get("state", "?")
        lines.append(f"── Service Order {so_id} [{so_state}] " + "─" * 20)
        services = services_by_so.get(so_id, [])
        cfs_list = [s for s in services if s.get("serviceType") == "CFS"]
        rfs_list = [s for s in services if s.get("serviceType") == "RFS"]
        for cfs in cfs_list:
            lines.append(
                f"  └─ CFS {cfs.get('id'):<8}  "
                f"{cfs.get('name', ''):<20} {cfs.get('state', '')}"
            )
            for rfs in rfs_list:
                lines.append(
                    f"       ├─ RFS {rfs.get('id'):<8}  "
                    f"{rfs.get('name', ''):<18} {rfs.get('state', '')}"
                )
                for task in tasks_by_service.get(rfs.get("id"), []):
                    dur = _fmt_duration(task)
                    lines.append(
                        f"       │     ├─ {task.get('id'):<7} "
                        f"{task.get('taskType', ''):<18} "
                        f"{task.get('state', ''):<10} {dur}"
                    )
        if not cfs_list and not rfs_list:
            lines.append("  (no services attached)")
        lines.append("")

    if subscription_id:
        lines.append(f"→ Subscription {subscription_id} activated")

    title = f"{oid}  {offering}  [{state}]"
    return box(lines, title=title, width=72)


def _fmt_duration(task: dict[str, Any]) -> str:
    from datetime import datetime

    started = task.get("startedAt")
    completed = task.get("completedAt")
    if not started or not completed:
        return ""
    try:
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        c = datetime.fromisoformat(completed.replace("Z", "+00:00"))
        sec = (c - s).total_seconds()
        return f"({sec:.1f}s)"
    except ValueError:
        return ""
