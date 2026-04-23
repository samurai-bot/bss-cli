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
class FakeClientsBundle:
    catalog: FakeCatalog = field(default_factory=FakeCatalog)


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
    return bundle


@pytest.fixture
def client(fake_clients: FakeClientsBundle):
    # Patch get_clients at every import site the routes use. Using
    # ``create=False`` so we don't accidentally create missing attrs.
    with patch("bss_self_serve.routes.landing.get_clients", return_value=fake_clients), \
         patch("bss_self_serve.routes.signup.get_clients", return_value=fake_clients):
        app = create_app(Settings())
        with TestClient(app) as c:
            yield c
