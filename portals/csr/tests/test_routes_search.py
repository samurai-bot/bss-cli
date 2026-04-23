"""Search route — name fragment + MSISDN paths."""

from __future__ import annotations

from conftest import sample_customer  # type: ignore[import-not-found]


def test_search_requires_login(client):  # type: ignore[no-untyped-def]
    resp = client.get("/search", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_empty_search_renders_form(authed_client):  # type: ignore[no-untyped-def]
    resp = authed_client.get("/search")
    assert resp.status_code == 200
    assert "Find a customer" in resp.text
    # Empty state not shown when no query was entered.
    assert "No matches" not in resp.text


def test_name_search_renders_results(authed_client, fake_clients):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_name = [
        sample_customer("CUST-aaa01", ("Ada", "Lovelace")),
        sample_customer("CUST-aaa02", ("Adam", "Smith")),
    ]
    resp = authed_client.get("/search?q=Ada")
    assert resp.status_code == 200
    assert "CUST-aaa01" in resp.text
    assert "Ada Lovelace" in resp.text
    assert "Adam Smith" in resp.text  # name_contains is fake-side filtered loosely


def test_msisdn_search_redirects_to_customer_360(authed_client, fake_clients):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_msisdn["90000042"] = sample_customer("CUST-byphone")
    fake_clients.crm.customers_by_id["CUST-byphone"] = sample_customer("CUST-byphone")

    resp = authed_client.get("/search?q=90000042", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/customer/CUST-byphone"


def test_msisdn_search_with_no_owner_renders_empty_results(authed_client, fake_clients):  # type: ignore[no-untyped-def]
    # Number not in the by_msisdn dict — find_customer_by_msisdn raises 404.
    resp = authed_client.get("/search?q=99999999")
    assert resp.status_code == 200
    assert "No matches" in resp.text


def test_msisdn_with_country_code_strips_plus(authed_client, fake_clients):  # type: ignore[no-untyped-def]
    fake_clients.crm.customers_by_msisdn["6590001234"] = sample_customer("CUST-cc")
    fake_clients.crm.customers_by_id["CUST-cc"] = sample_customer("CUST-cc")

    resp = authed_client.get("/search?q=%2B6590001234", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/customer/CUST-cc"
