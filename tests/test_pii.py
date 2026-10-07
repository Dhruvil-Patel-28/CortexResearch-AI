"""PII scrubbing tests — offline, deterministic regexes only."""

from __future__ import annotations

from guardrails.pii import scrub


def _kinds(redactions: list[dict]) -> dict[str, int]:
    return {r["kind"]: r["count"] for r in redactions}


def test_email_redacted_shape_preserving():
    text = "Contact jane.doe@example.com for details."
    clean, redactions = scrub(text)
    assert "jane.doe@example.com" not in clean
    assert "[EMAIL]" in clean
    assert "Contact [EMAIL] for details." == clean
    assert _kinds(redactions) == {"email": 1}


def test_phone_formats_redacted():
    for raw in ["+1 (415) 555-2671", "415-555-2671", "415.555.2671"]:
        clean, redactions = scrub(f"Call {raw} now")
        assert raw not in clean
        assert "[PHONE]" in clean
        assert _kinds(redactions) == {"phone": 1}


def test_ssn_redacted():
    clean, redactions = scrub("Their SSN is 078-05-1120 on file.")
    assert "078-05-1120" not in clean
    assert "[SSN]" in clean
    assert _kinds(redactions) == {"ssn": 1}


def test_credit_card_luhn_valid_redacted():
    clean, redactions = scrub("Card: 4111 1111 1111 1111 expires soon.")
    assert "4111 1111 1111 1111" not in clean
    assert "[CARD]" in clean
    assert _kinds(redactions) == {"card": 1}


def test_sixteen_digit_non_luhn_left_alone():
    text = "Order ref 1234 5678 9012 3456 shipped."
    clean, redactions = scrub(text)
    assert clean == text
    assert redactions == []


def test_openai_style_secret_redacted():
    clean, redactions = scrub("key: sk-proj-abc123def456ghi789jkl end")
    assert "sk-proj-abc123def456ghi789jkl" not in clean
    assert "[SECRET]" in clean
    assert _kinds(redactions) == {"secret": 1}


def test_aws_access_key_redacted():
    clean, redactions = scrub("Using AKIAIOSFODNN7EXAMPLE in prod")
    assert "AKIAIOSFODNN7EXAMPLE" not in clean
    assert _kinds(redactions) == {"secret": 1}


def test_github_and_slack_tokens_redacted():
    text = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 and xoxb-1234567890-abcdefghij"
    clean, redactions = scrub(text)
    assert "ghp_" not in clean
    assert "xoxb-" not in clean
    assert _kinds(redactions) == {"secret": 2}


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
    clean, redactions = scrub(f"token={jwt}")
    assert jwt not in clean
    assert _kinds(redactions) == {"secret": 1}


def test_api_key_assignment_keeps_name_redacts_value():
    clean, _ = scrub('api_key = "supersecret123value" in config')
    assert "supersecret123value" not in clean
    assert "api_key" in clean


def test_bearer_token_redacted():
    clean, redactions = scrub("Authorization: Bearer abc123def456ghi789jkl012")
    assert "abc123def456ghi789jkl012" not in clean
    assert _kinds(redactions) == {"secret": 1}


def test_clean_text_unchanged():
    text = "An ordinary paragraph about embedding models and SQLite indexes."
    clean, redactions = scrub(text)
    assert clean == text
    assert redactions == []


def test_multiple_kinds_aggregated():
    text = "Email bob@example.org or call 415-555-2671. Card 4111 1111 1111 1111."
    clean, redactions = scrub(text)
    kinds = _kinds(redactions)
    assert kinds["email"] == 1
    assert kinds["phone"] == 1
    assert kinds["card"] == 1
    assert "bob@example.org" not in clean
