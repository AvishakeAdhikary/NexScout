from nexscout.observability import REDACTED, redact_processor


def test_sensitive_keys_redacted() -> None:
    out = redact_processor(
        None,
        "info",
        {
            "event": "x",
            "password": "hunter2hunter2",
            "api_key": "abc",
            "session_token": "t",
            "Cookie": "a=b",
            "user": "ada",
        },
    )
    assert out["password"] == REDACTED
    assert out["api_key"] == REDACTED
    assert out["session_token"] == REDACTED
    assert out["Cookie"] == REDACTED
    assert out["user"] == "ada"


def test_nested_and_inline_secrets_redacted() -> None:
    out = redact_processor(
        None,
        "info",
        {
            "event": "calling provider with Bearer abcdefghijklmnop",
            "headers": {"Authorization": "Bearer xyz", "accept": "json"},
            "note": "key sk-ABCDEFGHIJKLMNOPQRSTUV leaked",
        },
    )
    assert "abcdefghijklmnop" not in out["event"]
    assert out["headers"]["Authorization"] == REDACTED
    assert out["headers"]["accept"] == "json"
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in out["note"]
