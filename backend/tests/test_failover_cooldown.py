"""TDD 測試：FailoverKeyState + classify_failover_error + compute_cooldown

對應卡片 #13106 P1-SH-14 步驟 1 — 只驗證純函式與資料結構。
"""
import dataclasses
import pytest

from app.core.failover_cooldown import (
    FailoverErrorKind,
    FailoverKeyState,
    classify_failover_error,
    compute_cooldown,
)


# ---------- classify_failover_error ----------

class TestClassifyFailoverError:
    def test_classify_rate_limit(self):
        assert classify_failover_error("HTTP 429 Too Many Requests") is FailoverErrorKind.rate_limit
        assert classify_failover_error("Rate limit exceeded") is FailoverErrorKind.rate_limit
        assert classify_failover_error("too many requests, slow down") is FailoverErrorKind.rate_limit
        assert classify_failover_error("quota exceeded for today") is FailoverErrorKind.rate_limit

    def test_classify_billing(self):
        assert classify_failover_error("insufficient_quota: account out of credit") is FailoverErrorKind.billing
        assert classify_failover_error("billing account suspended") is FailoverErrorKind.billing
        assert classify_failover_error("payment required") is FailoverErrorKind.billing
        assert classify_failover_error("your credit balance is too low") is FailoverErrorKind.billing

    def test_classify_auth(self):
        assert classify_failover_error("HTTP 401 Unauthorized") is FailoverErrorKind.auth
        assert classify_failover_error("unauthorized") is FailoverErrorKind.auth
        assert classify_failover_error("Invalid API key provided") is FailoverErrorKind.auth
        assert classify_failover_error("authentication failed") is FailoverErrorKind.auth

    def test_classify_model_not_found(self):
        assert classify_failover_error("HTTP 404 Not Found") is FailoverErrorKind.model_not_found
        assert classify_failover_error("model not found: gpt-xyz") is FailoverErrorKind.model_not_found
        assert classify_failover_error("unknown model id") is FailoverErrorKind.model_not_found

    def test_classify_other(self):
        assert classify_failover_error("connection reset") is FailoverErrorKind.other
        assert classify_failover_error("random gibberish") is FailoverErrorKind.other
        assert classify_failover_error("") is FailoverErrorKind.other


# ---------- compute_cooldown ----------

class TestComputeCooldown:
    def test_cooldown_formula_rate_limit_progression(self):
        # base=60, cap=3600, formula base * 5**(failures-1)
        assert compute_cooldown(FailoverErrorKind.rate_limit, 1) == 60
        assert compute_cooldown(FailoverErrorKind.rate_limit, 2) == 300
        assert compute_cooldown(FailoverErrorKind.rate_limit, 3) == 1500
        # failures=4: 60 * 125 = 7500 → clamp to 3600
        assert compute_cooldown(FailoverErrorKind.rate_limit, 4) == 3600
        assert compute_cooldown(FailoverErrorKind.rate_limit, 10) == 3600

    def test_cooldown_billing_cap_at_24h(self):
        # base=18000, failures=1 → 18000；failures=2 → 90000 clamp to 86400
        assert compute_cooldown(FailoverErrorKind.billing, 1) == 18000
        assert compute_cooldown(FailoverErrorKind.billing, 2) == 86400
        assert compute_cooldown(FailoverErrorKind.billing, 99) == 86400

    def test_auth_fixed_one_hour(self):
        assert compute_cooldown(FailoverErrorKind.auth, 1) == 3600
        assert compute_cooldown(FailoverErrorKind.auth, 5) == 3600
        assert compute_cooldown(FailoverErrorKind.auth, 100) == 3600

    def test_model_not_found_zero(self):
        assert compute_cooldown(FailoverErrorKind.model_not_found, 1) == 0
        assert compute_cooldown(FailoverErrorKind.model_not_found, 50) == 0

    def test_other_follows_rate_limit_shape(self):
        # base=60, cap=3600
        assert compute_cooldown(FailoverErrorKind.other, 1) == 60
        assert compute_cooldown(FailoverErrorKind.other, 2) == 300
        assert compute_cooldown(FailoverErrorKind.other, 10) == 3600


# ---------- FailoverKeyState ----------

class TestFailoverKeyState:
    def test_default_values(self):
        state = FailoverKeyState()
        assert state.failures == 0
        assert state.last_failure_at == 0.0
        assert state.cooldown_until == 0.0

    def test_state_is_immutable(self):
        state = FailoverKeyState(failures=1, last_failure_at=100.0, cooldown_until=160.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.failures = 2  # type: ignore[misc]

    def test_dataclass_replace_returns_new_instance(self):
        original = FailoverKeyState()
        updated = dataclasses.replace(original, failures=original.failures + 1)
        assert original.failures == 0
        assert updated.failures == 1
        assert updated is not original
