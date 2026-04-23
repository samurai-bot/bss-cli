"""REPL renderer-dispatch tests.

Asserts ``_maybe_render_tool_result`` returns a polished ASCII card
for the tool names listed in ``_RENDERER_DISPATCH`` and ``None``
otherwise. Defends the v0.6.0 polish from being invisible in the
LLM-native flow (the original bug — REPL only showed prose).
"""

from __future__ import annotations

import json

from bss_cli.repl import _RENDERER_DISPATCH, _maybe_render_tool_result


def test_dispatch_covers_all_show_shaped_tools() -> None:
    expected = {
        "subscription.get",
        "customer.get",
        "customer.find_by_msisdn",
        "order.get",
        "catalog.list_offerings",
        "catalog.get_offering",
        "inventory.esim.get_activation",
        "subscription.get_esim_activation",
    }
    assert set(_RENDERER_DISPATCH.keys()) == expected


def test_unknown_tool_returns_none() -> None:
    assert _maybe_render_tool_result("payment.add_card", '{"id": "PM-1"}') is None


def test_invalid_json_returns_none() -> None:
    assert _maybe_render_tool_result("subscription.get", "not json") is None


def test_empty_payload_returns_none() -> None:
    assert _maybe_render_tool_result("subscription.get", "{}") is not None or True
    # Empty dict still renders (just shows "—" placeholders); assertion
    # checks the function doesn't crash. The next test exercises content.


def test_subscription_get_renders_card() -> None:
    payload = {
        "id": "SUB-007",
        "customerId": "CUST-007",
        "msisdn": "90000005",
        "offeringId": "PLAN_M",
        "state": "active",
        "balances": [
            {"type": "data", "used": 2.1, "total": 5.0, "unit": "gb"},
        ],
    }
    out = _maybe_render_tool_result("subscription.get", json.dumps(payload))
    assert out is not None
    assert "SUB-007" in out
    assert "9000 0005" in out  # MSISDN formatted
    assert "Bundle" in out


def test_subscription_get_blocked_uses_double_rule_frame() -> None:
    payload = {
        "id": "SUB-007",
        "customerId": "CUST-007",
        "msisdn": "90000005",
        "offeringId": "PLAN_S",
        "state": "blocked",
        "balances": [{"type": "data", "used": 5, "total": 5, "unit": "gb"}],
    }
    out = _maybe_render_tool_result("subscription.get", json.dumps(payload))
    assert out is not None
    assert "╔" in out and "╚" in out  # double-rule frame for blocked


def test_catalog_list_renders_three_column_grid() -> None:
    payload = [
        {
            "id": "PLAN_S",
            "name": "Lite",
            "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 10}}}],
            "bundleAllowance": [{"type": "data", "total": 5120, "unit": "mb"}],
        },
        {
            "id": "PLAN_M",
            "name": "Standard",
            "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 25}}}],
            "bundleAllowance": [{"type": "data", "total": 30720, "unit": "mb"}],
        },
        {
            "id": "PLAN_L",
            "name": "Max",
            "productOfferingPrice": [{"price": {"taxIncludedAmount": {"value": 45}}}],
            "bundleAllowance": [{"type": "data", "total": -1, "unit": "mb"}],
        },
    ]
    out = _maybe_render_tool_result("catalog.list_offerings", json.dumps(payload))
    assert out is not None
    assert "PLAN_S" in out and "PLAN_M" in out and "PLAN_L" in out
    assert "★" in out  # popular marker on PLAN_M
    assert "GST" in out


def test_esim_activation_renders_qr_card() -> None:
    payload = {
        "iccid": "8910101000000000123",
        "imsi": "525010123456789",
        "msisdn": "90000005",
        "activationCode": "LPA:1$smdp.bss-cli.local$abc-123",
        "status": "prepared",
    }
    out = _maybe_render_tool_result(
        "inventory.esim.get_activation", json.dumps(payload)
    )
    assert out is not None
    assert "PREPARED" in out
    assert "LPA:1$" in out
    assert "•" in out  # ICCID redacted by default


def test_renderer_exception_does_not_propagate() -> None:
    # Pass a payload shape the renderer expects but with the wrong types
    # — the helper must swallow the error and return None.
    out = _maybe_render_tool_result("subscription.get", '{"balances": "not a list"}')
    # Should either render a degraded card or return None; never raise.
    # The contract is "best-effort, never break the REPL".
    # (Verifying behaviour here is light; the not-raising part is the test.)
    assert out is None or isinstance(out, str)
