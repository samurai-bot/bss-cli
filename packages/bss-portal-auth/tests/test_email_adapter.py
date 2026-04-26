"""Email adapter — selection, LoggingEmailAdapter file IO, NoopEmailAdapter records."""

from __future__ import annotations

import pytest

from bss_portal_auth import (
    LoggingEmailAdapter,
    NoopEmailAdapter,
    SmtpEmailAdapter,
    select_adapter,
)
from bss_portal_auth.test_helpers import last_login_codes, last_step_up_code


def test_noop_adapter_records_login_otp_and_magic_link():
    adapter = NoopEmailAdapter()
    adapter.send_login("ada@example.sg", "424242", "MAGIC_LINK_TOKEN")
    rec = last_login_codes(adapter, "ada@example.sg")
    assert rec["otp"] == "424242"
    assert rec["magic_link"] == "MAGIC_LINK_TOKEN"


def test_noop_adapter_scopes_step_up_by_action_label():
    adapter = NoopEmailAdapter()
    adapter.send_step_up("ada@example.sg", "111111", "subscription.terminate")
    adapter.send_step_up("ada@example.sg", "222222", "payment.remove_method")
    assert last_step_up_code(adapter, "ada@example.sg", "subscription.terminate") == "111111"
    assert last_step_up_code(adapter, "ada@example.sg", "payment.remove_method") == "222222"


def test_logging_adapter_writes_otp_and_magic_link_to_mailbox(tmp_path):
    mailbox = tmp_path / "mailbox.log"
    adapter = LoggingEmailAdapter(mailbox)
    adapter.send_login("ada@example.sg", "424242", "MAGIC_LINK_TOKEN")
    body = mailbox.read_text()
    assert "ada@example.sg" in body
    assert "OTP: 424242" in body
    assert "MAGIC_LINK_TOKEN" in body


def test_logging_adapter_appends_each_send(tmp_path):
    mailbox = tmp_path / "mailbox.log"
    adapter = LoggingEmailAdapter(mailbox)
    adapter.send_login("a@x", "111111", "ml1")
    adapter.send_login("a@x", "222222", "ml2")
    body = mailbox.read_text()
    assert "111111" in body and "222222" in body
    # Two separator lines = two sends.
    assert body.count("===") >= 4  # opening + closing per send


def test_smtp_adapter_construct_raises():
    """v0.8 must NOT silently fall back to a no-op SMTP adapter."""
    with pytest.raises(NotImplementedError, match="reserved for v1.0"):
        SmtpEmailAdapter()


def test_select_adapter_logging(tmp_path):
    a = select_adapter("logging", tmp_path / "m.log")
    assert isinstance(a, LoggingEmailAdapter)


def test_select_adapter_noop(tmp_path):
    a = select_adapter("noop", tmp_path / "m.log")
    assert isinstance(a, NoopEmailAdapter)


def test_select_adapter_smtp_fails_fast(tmp_path):
    with pytest.raises(NotImplementedError):
        select_adapter("smtp", tmp_path / "m.log")


def test_select_adapter_unknown_value_raises(tmp_path):
    with pytest.raises(RuntimeError, match="Unknown BSS_PORTAL_EMAIL_ADAPTER"):
        select_adapter("postal-pigeon", tmp_path / "m.log")
