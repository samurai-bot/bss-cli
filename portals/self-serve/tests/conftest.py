"""Shared fixtures — mocked ``get_clients()`` so route tests don't need
a real catalog service. Each test can override the canned offering list
by mutating ``fake_clients.catalog.offerings`` before the request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bss_self_serve.config import Settings
from bss_self_serve.main import create_app


@dataclass
class FakeCatalog:
    offerings: list[dict[str, Any]] = field(default_factory=list)

    async def list_offerings(self) -> list[dict[str, Any]]:
        return list(self.offerings)


@dataclass
class FakeSubscription:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get(self, subscription_id: str) -> dict[str, Any]:
        if subscription_id not in self.records:
            raise KeyError(subscription_id)
        return dict(self.records[subscription_id])


@dataclass
class FakeInventory:
    activations: dict[str, dict[str, Any]] = field(default_factory=dict)
    msisdns: list[dict[str, Any]] = field(default_factory=list)

    async def get_activation_code(self, iccid: str) -> dict[str, Any]:
        if iccid not in self.activations:
            raise KeyError(iccid)
        return dict(self.activations[iccid])

    async def list_msisdns(
        self,
        *,
        state: str | None = None,
        prefix: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        out = list(self.msisdns)
        if state:
            out = [n for n in out if n.get("status") == state]
        if prefix:
            out = [n for n in out if n["msisdn"].startswith(prefix)]
        return out[:limit]


@dataclass
class FakeCOM:
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        if order_id not in self.orders:
            raise KeyError(order_id)
        return dict(self.orders[order_id])


@dataclass
class FakeClientsBundle:
    catalog: FakeCatalog = field(default_factory=FakeCatalog)
    subscription: FakeSubscription = field(default_factory=FakeSubscription)
    inventory: FakeInventory = field(default_factory=FakeInventory)
    com: FakeCOM = field(default_factory=FakeCOM)


SAMPLE_OFFERINGS = [
    {
        "id": "PLAN_S",
        "name": "Sidekick",
        "productOfferingPrice": [
            {"price": {"taxIncludedAmount": {"value": 15, "unit": "SGD"}}}
        ],
        "bundleAllowance": [
            {"type": "data", "total": 5120, "unit": "mb"},
            {"type": "voice", "total": 100, "unit": "min"},
            {"type": "sms", "total": 100, "unit": "sms"},
        ],
    },
    {
        "id": "PLAN_M",
        "name": "Mainline",
        "productOfferingPrice": [
            {"price": {"taxIncludedAmount": {"value": 25, "unit": "SGD"}}}
        ],
        "bundleAllowance": [
            {"type": "data", "total": 20480, "unit": "mb"},
            {"type": "voice", "total": 300, "unit": "min"},
            {"type": "sms", "total": -1, "unit": "sms"},
        ],
    },
    {
        "id": "PLAN_L",
        "name": "Long Haul",
        "productOfferingPrice": [
            {"price": {"taxIncludedAmount": {"value": 45, "unit": "SGD"}}}
        ],
        "bundleAllowance": [
            {"type": "data", "total": -1, "unit": "mb"},
            {"type": "voice", "total": -1, "unit": "min"},
            {"type": "sms", "total": -1, "unit": "sms"},
        ],
    },
]


@pytest.fixture
def fake_clients() -> FakeClientsBundle:
    bundle = FakeClientsBundle()
    bundle.catalog.offerings = list(SAMPLE_OFFERINGS)
    bundle.inventory.msisdns = [
        {"msisdn": f"9000000{i}", "status": "available", "reserved_at": None}
        for i in range(2, 8)
    ] + [
        {"msisdn": "90000010", "status": "available", "reserved_at": None},
        # an already-assigned one to prove the status filter works
        {"msisdn": "90000001", "status": "assigned", "reserved_at": "2026-04-23T00:00:00Z"},
    ]
    return bundle


@pytest.fixture
def client(fake_clients: FakeClientsBundle):
    # Patch get_clients at every import site the routes use. Using
    # ``create=False`` so we don't accidentally create missing attrs.
    with patch("bss_self_serve.routes.landing.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.activation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.confirmation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.msisdn_picker.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            yield c
