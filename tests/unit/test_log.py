from __future__ import annotations

import logging

import pytest

from qa_assistant.log import REDACTED, configure_logging, redact


def test_redacts_known_secret() -> None:
    assert redact("token=s3cr3t-value used", ["s3cr3t-value"]) == f"token={REDACTED} used"


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Basic dXNlcjpub3RhcmVhbHRva2Vu",
        "authorization=Bearer abcdefghijklmnop",
        "sent Bearer abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_redacts_auth_headers(text: str) -> None:
    redacted = redact(text)
    assert "dXNlcjpub3RhcmVhbHRva2Vu" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert REDACTED in redacted


def test_logs_go_to_stderr_and_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", secrets=["very-secret-token"])
    try:
        logging.getLogger("qa_assistant.test").info("calling with %s", "very-secret-token")
        captured = capsys.readouterr()
    finally:
        logging.getLogger().handlers.clear()
    assert captured.out == ""  # stdout is reserved for the MCP transport
    assert "very-secret-token" not in captured.err
    assert REDACTED in captured.err
