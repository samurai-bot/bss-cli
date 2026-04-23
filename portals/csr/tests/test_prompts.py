"""build_csr_prompt — context injection + KNOWN_LEADS shape."""

from __future__ import annotations

from bss_csr.prompts import KNOWN_LEADS, build_csr_prompt


def test_prompt_includes_operator_customer_question_and_snapshot() -> None:
    p = build_csr_prompt(
        operator_id="csr-demo-001",
        customer_id="CUST-test01",
        question="Why is their data not working?",
        customer_snapshot={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "status": "active",
            "kyc_status": "verified",
        },
        subscription_snapshot=[
            {"id": "SUB-007", "state": "blocked", "offering": "PLAN_M"},
        ],
    )
    assert "csr-demo-001" in p
    assert "CUST-test01" in p
    assert "Why is their data not working?" in p
    assert "Ada Lovelace" in p
    assert "verified" in p
    assert "SUB-007" in p
    assert "blocked" in p
    assert "PLAN_M" in p


def test_prompt_handles_zero_subscriptions() -> None:
    p = build_csr_prompt(
        operator_id="csr",
        customer_id="CUST-x",
        question="?",
        customer_snapshot={"name": "x", "email": "", "status": "?", "kyc_status": "?"},
        subscription_snapshot=[],
    )
    assert "no subscriptions on file" in p


def test_prompt_lists_known_leads() -> None:
    p = build_csr_prompt(
        operator_id="csr",
        customer_id="CUST-x",
        question="?",
        customer_snapshot={"name": "x", "email": "", "status": "?", "kyc_status": "?"},
        subscription_snapshot=[],
    )
    for lead in KNOWN_LEADS:
        assert lead["question"] in p


def test_prompt_pins_destructive_constraints() -> None:
    p = build_csr_prompt(
        operator_id="csr",
        customer_id="CUST-x",
        question="?",
        customer_snapshot={"name": "x", "email": "", "status": "?", "kyc_status": "?"},
        subscription_snapshot=[],
    )
    for forbidden in ("subscription.terminate", "customer.close", "ticket.cancel"):
        assert forbidden in p
