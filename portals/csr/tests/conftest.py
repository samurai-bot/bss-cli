"""Shared fixtures for CSR portal tests.

Mocks ``get_clients()`` at every route's import site so tests run
without a live BSS stack. Each test can override the canned data on
the fixture before exercising the route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bss_csr.config import Settings
from bss_csr.main import create_app


# ─── Fake clients ────────────────────────────────────────────────────


@dataclass
class FakeCRM:
    customers_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    customers_by_msisdn: dict[str, dict[str, Any]] = field(default_factory=dict)
    customers_by_name: list[dict[str, Any]] = field(default_factory=list)
    cases: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    interactions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        if customer_id not in self.customers_by_id:
            from bss_clients.errors import ClientError
            raise ClientError(404, f"Customer {customer_id} not found")
        return dict(self.customers_by_id[customer_id])

    async def find_customer_by_msisdn(self, msisdn: str) -> dict[str, Any]:
        if msisdn not in self.customers_by_msisdn:
            from bss_clients.errors import ClientError
            raise ClientError(404, f"No customer for {msisdn}")
        return dict(self.customers_by_msisdn[msisdn])

    async def list_customers(
        self, *, name_contains: str | None = None, **_kw: Any
    ) -> list[dict[str, Any]]:
        if not name_contains:
            return list(self.customers_by_name)
        return [
            c for c in self.customers_by_name
            if name_contains.lower() in (
                f"{(c.get('individual') or {}).get('givenName','')} "
                f"{(c.get('individual') or {}).get('familyName','')}".lower()
            )
        ]

    async def list_cases(self, *, customer_id: str) -> list[dict[str, Any]]:
        return list(self.cases.get(customer_id, []))

    async def list_interactions(
        self, *, customer_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return list(self.interactions.get(customer_id, []))[:limit]


@dataclass
class FakeSubscription:
    by_customer: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def list_for_customer(self, customer_id: str) -> list[dict[str, Any]]:
        return list(self.by_customer.get(customer_id, []))

    async def get(self, subscription_id: str) -> dict[str, Any]:
        if subscription_id not in self.by_id:
            from bss_clients.errors import ClientError
            raise ClientError(404, "no such sub")
        return dict(self.by_id[subscription_id])


@dataclass
class FakePayment:
    by_customer: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def list_methods(self, *, customer_id: str) -> list[dict[str, Any]]:
        return list(self.by_customer.get(customer_id, []))


@dataclass
class FakeBundle:
    crm: FakeCRM = field(default_factory=FakeCRM)
    subscription: FakeSubscription = field(default_factory=FakeSubscription)
    payment: FakePayment = field(default_factory=FakePayment)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def fake_clients() -> FakeBundle:
    return FakeBundle()


@pytest.fixture
def client(fake_clients: FakeBundle):
    with patch("bss_csr.routes.search.get_clients", return_value=fake_clients), \
         patch("bss_csr.routes.customer.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            yield c


@pytest.fixture
def authed_client(client):
    """TestClient with a logged-in operator cookie set."""
    login = client.post(
        "/login", data={"username": "test-csr"}, follow_redirects=False
    )
    assert login.status_code == 303
    # TestClient persists cookies across requests automatically.
    yield client


# ─── Sample TMF-shaped payloads ──────────────────────────────────────


def sample_customer(customer_id="CUST-test01", name=("Ada", "Lovelace")) -> dict:
    return {
        "id": customer_id,
        "individual": {"givenName": name[0], "familyName": name[1]},
        "contactMedium": [
            {"mediumType": "email", "value": f"{customer_id.lower()}@example.com"},
            {"mediumType": "mobile", "value": "+6590001234"},
        ],
        "status": "active",
        "kycStatus": "verified",
        "customerSince": "2026-04-23T00:00:00Z",
    }


def sample_subscription(
    sub_id="SUB-007",
    customer_id="CUST-test01",
    state="active",
    offering="PLAN_M",
    msisdn="90000042",
    balances=None,
) -> dict:
    return {
        "id": sub_id,
        "customerId": customer_id,
        "state": state,
        "offeringId": offering,
        "msisdn": msisdn,
        "iccid": "8910101000000000001",
        "balances": balances or [
            {"allowanceType": "data", "remaining": 5120, "total": 5120, "unit": "mb"},
            {"allowanceType": "voice", "remaining": -1, "total": -1, "unit": "min"},
        ],
        "nextRenewalAt": "2026-05-23T00:00:00Z",
    }
