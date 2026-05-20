"""Permanent-failure classification + parse_result_line."""

from __future__ import annotations

import pytest

from nexscout.apply.result_codes import (
    PERMANENT_FAILURE_REASONS,
    is_permanent_failure,
    parse_result_line,
)


class TestPermanentFailure:
    @pytest.mark.parametrize(
        "reason",
        [
            "expired",
            "captcha",
            "login_issue",
            "not_eligible_location",
            "not_eligible_salary",
            "already_applied",
            "account_required",
            "not_a_job_application",
            "unsafe_permissions",
            "unsafe_verification",
            "sso_required",
            "site_blocked",
            "cloudflare_blocked",
            "blocked_by_cloudflare",
        ],
    )
    def test_listed_reasons_are_permanent(self, reason: str) -> None:
        assert is_permanent_failure(reason)
        assert reason in PERMANENT_FAILURE_REASONS or any(
            reason.startswith(p) for p in ("site_blocked", "cloudflare", "blocked_by")
        )

    @pytest.mark.parametrize(
        "reason",
        ["site_blocked_legacy", "cloudflare_captcha", "blocked_by_glassdoor", "cloudflare"],
    )
    def test_prefix_match_permanent(self, reason: str) -> None:
        assert is_permanent_failure(reason)

    @pytest.mark.parametrize("reason", ["stuck", "page_error", "timeout", "no_result_line", None, ""])
    def test_transient_reasons_are_not_permanent(self, reason: str | None) -> None:
        assert not is_permanent_failure(reason)

    def test_case_insensitive(self) -> None:
        assert is_permanent_failure("Expired")
        assert is_permanent_failure("CLOUDFLARE_BLOCKED")


class TestParseResultLine:
    def test_applied(self) -> None:
        assert parse_result_line("RESULT:APPLIED") == ("APPLIED", None)

    def test_failed_with_reason(self) -> None:
        assert parse_result_line("RESULT:FAILED:sso_required") == ("FAILED", "sso_required")

    def test_no_result_prefix(self) -> None:
        code, reason = parse_result_line("hello")
        assert code == "FAILED"
        assert reason == "no_result_line"

    def test_strips_whitespace(self) -> None:
        assert parse_result_line("  RESULT:CAPTCHA  ") == ("CAPTCHA", None)

    def test_reason_with_colon(self) -> None:
        code, reason = parse_result_line("RESULT:FAILED:custom: trailing colon")
        assert code == "FAILED"
        assert reason == "custom: trailing colon"
