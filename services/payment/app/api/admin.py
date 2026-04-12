"""Payment admin router — wipes the ``payment`` schema."""

from __future__ import annotations

from bss_admin import ResetPlan, TableReset, admin_router

_OPERATIONAL = (
    TableReset("payment_attempt"),
    TableReset("payment_method"),
)

router = admin_router(
    service_name="payment",
    plans=[ResetPlan(schema="payment", tables=_OPERATIONAL)],
)
