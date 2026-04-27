"""Shared fixtures — mocked ``get_clients()`` so route tests don't need
a real catalog service. Each test can override the canned offering list
by mutating ``fake_clients.catalog.offerings`` before the request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

# v0.8 — portal lifespan calls ``validate_pepper_present()``. Set a
# fixed test pepper BEFORE importing the app modules so the lifespan
# doesn't fail when TestClient(app) runs the startup hooks.
os.environ.setdefault(
    "BSS_PORTAL_TOKEN_PEPPER",
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
)
# Tests use the in-memory NoopEmailAdapter — no file I/O on /tmp.
os.environ.setdefault("BSS_PORTAL_EMAIL_ADAPTER", "noop")

import pytest
from fastapi.testclient import TestClient

from bss_self_serve.config import Settings
from bss_self_serve.main import create_app


@dataclass
class FakeCatalog:
    offerings: list[dict[str, Any]] = field(default_factory=list)
    vas_offerings: list[dict[str, Any]] = field(default_factory=list)

    async def list_offerings(self) -> list[dict[str, Any]]:
        return list(self.offerings)

    async def list_vas(self) -> list[dict[str, Any]]:
        return list(self.vas_offerings)


@dataclass
class FakeSubscription:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_customer: dict[str, list[str]] = field(default_factory=dict)
    balances: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    purchase_vas_calls: list[tuple[str, str]] = field(default_factory=list)
    # v0.10 — tests pre-seed an exception here to simulate a server-side
    # PolicyViolation on the next call to ``purchase_vas`` etc.
    next_error: Exception | None = None

    async def get(self, subscription_id: str) -> dict[str, Any]:
        if subscription_id not in self.records:
            raise KeyError(subscription_id)
        return dict(self.records[subscription_id])

    async def list_for_customer(self, customer_id: str) -> list[dict[str, Any]]:
        ids = self.by_customer.get(customer_id, [])
        return [dict(self.records[i]) for i in ids if i in self.records]

    async def get_balance(self, subscription_id: str) -> list[dict[str, Any]]:
        return [dict(b) for b in self.balances.get(subscription_id, [])]

    async def purchase_vas(
        self, subscription_id: str, vas_offering_id: str
    ) -> dict[str, Any]:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        self.purchase_vas_calls.append((subscription_id, vas_offering_id))
        if subscription_id in self.records:
            return dict(self.records[subscription_id])
        raise KeyError(subscription_id)


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
class FakePayment:
    methods_by_customer: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    create_calls: list[dict[str, Any]] = field(default_factory=list)
    remove_calls: list[str] = field(default_factory=list)
    set_default_calls: list[str] = field(default_factory=list)
    next_error: Exception | None = None

    async def list_methods(self, customer_id: str) -> list[dict[str, Any]]:
        return [dict(m) for m in self.methods_by_customer.get(customer_id, [])]

    async def create_payment_method(
        self,
        *,
        customer_id: str,
        card_token: str,
        last4: str,
        brand: str,
        exp_month: int = 12,
        exp_year: int = 2030,
        tokenization_provider: str = "sandbox",
        country: str | None = "SG",
    ) -> dict[str, Any]:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        record = {
            "customer_id": customer_id,
            "card_token": card_token,
            "last4": last4,
            "brand": brand,
            "exp_month": exp_month,
            "exp_year": exp_year,
        }
        self.create_calls.append(record)
        new_id = f"PM-{len(self.create_calls):04d}"
        existing = self.methods_by_customer.setdefault(customer_id, [])
        is_default = len(existing) == 0
        method = {
            "id": new_id,
            "customerId": customer_id,
            "brand": brand,
            "last4": last4,
            "expMonth": exp_month,
            "expYear": exp_year,
            "isDefault": is_default,
        }
        existing.append(method)
        return dict(method)

    async def remove_method(self, method_id: str) -> dict[str, Any]:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        self.remove_calls.append(method_id)
        for cust_id, methods in self.methods_by_customer.items():
            for m in methods:
                if m["id"] == method_id:
                    methods.remove(m)
                    return {"id": method_id, "removed": True}
        raise KeyError(method_id)

    async def set_default_method(self, method_id: str) -> dict[str, Any]:
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        self.set_default_calls.append(method_id)
        for cust_id, methods in self.methods_by_customer.items():
            target = next((m for m in methods if m["id"] == method_id), None)
            if target is not None:
                for m in methods:
                    m["isDefault"] = (m["id"] == method_id)
                return dict(target)
        raise KeyError(method_id)


@dataclass
class FakeClientsBundle:
    catalog: FakeCatalog = field(default_factory=FakeCatalog)
    subscription: FakeSubscription = field(default_factory=FakeSubscription)
    inventory: FakeInventory = field(default_factory=FakeInventory)
    com: FakeCOM = field(default_factory=FakeCOM)
    # v0.10 — added so post-login route tests can pre-seed responses.
    payment: FakePayment = field(default_factory=FakePayment)
    provisioning: Any = None
    crm: Any = None


SAMPLE_VAS = [
    {
        "id": "VAS_DATA_1GB",
        "name": "Data Top-Up 1GB",
        "priceAmount": 3.00,
        "currency": "SGD",
        "allowanceType": "data",
        "allowanceQuantity": 1024,
        "allowanceUnit": "mb",
        "expiryHours": None,
    },
    {
        "id": "VAS_DATA_5GB",
        "name": "Data Top-Up 5GB",
        "priceAmount": 12.00,
        "currency": "SGD",
        "allowanceType": "data",
        "allowanceQuantity": 5120,
        "allowanceUnit": "mb",
        "expiryHours": None,
    },
    {
        "id": "VAS_UNLIMITED_DAY",
        "name": "Unlimited Data Day Pass",
        "priceAmount": 5.00,
        "currency": "SGD",
        "allowanceType": "data",
        "allowanceQuantity": -1,
        "allowanceUnit": "mb",
        "expiryHours": 24,
    },
]


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
    bundle.catalog.vas_offerings = list(SAMPLE_VAS)
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
    # routes/landing.py is the dashboard now (no catalog reads); the
    # public plan-card browse moved to routes/welcome.py at /plans.
    with patch("bss_self_serve.routes.welcome.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.activation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.confirmation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.msisdn_picker.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.landing.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.top_up.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.payment_methods.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            yield c


@pytest.fixture
def authed_client(fake_clients: FakeClientsBundle):
    """TestClient with a pre-attached verified-email session cookie.

    v0.8 — the signup funnel routes (/signup/*, /agent/events/*) require
    an identity. This fixture seeds one via a separate setup engine, then
    attaches the session id as a cookie. Tests that hit gated routes
    use this fixture; tests for public surfaces use ``client``.

    Implementation note: we have to seed the session on a different
    engine than the app's lifespan engine because TestClient spins each
    test on a fresh asyncio loop and asyncpg connections are loop-bound.
    """
    import asyncio
    import os
    from pathlib import Path
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from bss_portal_auth.test_helpers import create_test_session
    from bss_self_serve.middleware import PORTAL_SESSION_COOKIE

    repo_root = Path(__file__).resolve().parents[3]

    class _DbSettings(BaseSettings):
        BSS_DB_URL: str = ""
        model_config = SettingsConfigDict(
            env_file=repo_root / ".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

    db_url = _DbSettings().BSS_DB_URL or os.environ.get("BSS_DB_URL", "")
    if not db_url:
        pytest.fail("BSS_DB_URL is not set. Export it or add to .env.")
    os.environ["BSS_DB_URL"] = db_url

    async def _seed():
        engine = create_async_engine(db_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            await s.execute(text(
                "TRUNCATE portal_auth.login_attempt, portal_auth.session, "
                "portal_auth.login_token, portal_auth.identity RESTART IDENTITY CASCADE"
            ))
            await s.commit()
        async with factory() as s:
            sess, identity = await create_test_session(
                s, email="ada@example.sg", verified=True
            )
            await s.commit()
            sid = sess.id
            iid = identity.id
        await engine.dispose()
        return sid, iid

    async def _scrub():
        engine = create_async_engine(db_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            await s.execute(text(
                "TRUNCATE portal_auth.login_attempt, portal_auth.session, "
                "portal_auth.login_token, portal_auth.identity RESTART IDENTITY CASCADE"
            ))
            await s.commit()
        await engine.dispose()

    session_id, identity_id = asyncio.run(_seed())

    # routes/landing.py is the dashboard now (no catalog reads); the
    # public plan-card browse moved to routes/welcome.py at /plans.
    with patch("bss_self_serve.routes.welcome.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.activation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.confirmation.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.msisdn_picker.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.landing.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.top_up.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.payment_methods.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            c.cookies.set(PORTAL_SESSION_COOKIE, session_id)
            # Stash for tests that want to assert against the seeded ids.
            c.app.state.test_identity_id = identity_id
            c.app.state.test_session_id = session_id
            yield c

    asyncio.run(_scrub())
