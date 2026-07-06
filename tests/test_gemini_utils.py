"""
InsureIQ — Tests: shared Gemini utilities (gemini_utils.py)
Run with: pytest tests/test_gemini_utils.py -v

No real API key or network — the Gemini model is a stub. These verify the quota /
rate-limit detection and that call_gemini_with_retry fails fast with a clear,
reviewer-friendly GeminiQuotaExhaustedError instead of an opaque RuntimeError.
"""

import pytest

from agents.gemini_utils import (
    GeminiQuotaExhaustedError,
    _is_quota_error,
    call_gemini_with_retry,
    parse_gemini_json_response,
)


class _StubModel:
    """Minimal stand-in for a Gemini GenerativeModel.

    Raises `exc` on the first N calls, then returns a response whose `.text` is
    `text`. Records how many times it was called so we can assert retry behaviour.
    """

    def __init__(self, exc=None, fail_times=0, text="ok"):
        self._exc = exc
        self._fail_times = fail_times
        self._text = text
        self.calls = 0

    def generate_content(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return type("Resp", (), {"text": self._text})()


# ─── quota detection ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "429 Resource has been exhausted (e.g. check quota).",
    "You exceeded your current quota, please check your plan and billing.",
    "RateLimitError: too many requests",
    "google.api_core.exceptions.ResourceExhausted: 429",
])
def test_is_quota_error_true_for_quota_signals(message):
    assert _is_quota_error(Exception(message)) is True


def test_is_quota_error_detects_by_exception_type_name():
    class ResourceExhausted(Exception):
        pass
    assert _is_quota_error(ResourceExhausted("boom")) is True


@pytest.mark.parametrize("message", [
    "Connection reset by peer",
    "Invalid API key",
    "500 Internal Server Error",
    "JSONDecodeError: expecting value",
])
def test_is_quota_error_false_for_unrelated_errors(message):
    assert _is_quota_error(Exception(message)) is False


# ─── call_gemini_with_retry ───────────────────────────────────────────────────

def test_quota_error_raises_friendly_exception_without_retrying():
    # A quota rejection should fail fast (no wasted retries) with the clear message.
    model = _StubModel(exc=Exception("429 quota exceeded"), fail_times=99)
    with pytest.raises(GeminiQuotaExhaustedError) as exc:
        call_gemini_with_retry(model, "prompt")
    assert model.calls == 1                       # failed fast, did not retry
    assert "quota exhausted" in str(exc.value).lower()
    assert "pytest" in str(exc.value).lower()     # actionable guidance included


def test_non_quota_error_retries_then_raises_runtimeerror(monkeypatch):
    # A generic error should retry MAX_RETRIES times, then raise a plain RuntimeError
    # (not the quota-specific type).
    monkeypatch.setattr("agents.gemini_utils.time.sleep", lambda *_: None)  # no real waiting
    model = _StubModel(exc=Exception("connection reset"), fail_times=99)
    with pytest.raises(RuntimeError) as exc:
        call_gemini_with_retry(model, "prompt")
    assert not isinstance(exc.value, GeminiQuotaExhaustedError)
    assert model.calls == 3
    assert "failed after 3 attempts" in str(exc.value).lower()


def test_transient_error_then_success(monkeypatch):
    # One transient failure, then success — the call should recover and return text.
    monkeypatch.setattr("agents.gemini_utils.time.sleep", lambda *_: None)
    model = _StubModel(exc=Exception("temporary blip"), fail_times=1, text="recovered")
    assert call_gemini_with_retry(model, "prompt") == "recovered"
    assert model.calls == 2


def test_parse_gemini_json_strips_fences():
    assert parse_gemini_json_response('```json\n{"a": 1}\n```') == {"a": 1}
