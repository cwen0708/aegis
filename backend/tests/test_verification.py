"""Anti-fabrication 驗證框架測試"""
import logging
import pytest
from app.core.verification import (
    BaseVerifier,
    TestOutputVerifier,
    VerificationResult,
    VerifiedRegistry,
    create_default_registry,
)
from app.hooks import TaskContext
from app.hooks.verification import VerificationHook


# ════════════════════════════════════════
# VerificationResult
# ════════════════════════════════════════

class TestVerificationResult:
    def test_creation_passed(self):
        r = VerificationResult(
            passed=True,
            verifier_name="TestVerifier",
            evidence="",
            details="OK",
        )
        assert r.passed is True
        assert r.verifier_name == "TestVerifier"
        assert r.evidence == ""
        assert r.details == "OK"

    def test_creation_failed(self):
        r = VerificationResult(
            passed=False,
            verifier_name="TestVerifier",
            evidence="exit_code=1",
            details="mismatch",
        )
        assert r.passed is False
        assert r.evidence == "exit_code=1"

    def test_immutable(self):
        r = VerificationResult(passed=True, verifier_name="X", evidence="")
        with pytest.raises(AttributeError):
            r.passed = False  # type: ignore[misc]


# ════════════════════════════════════════
# TestOutputVerifier
# ════════════════════════════════════════

class TestTestOutputVerifier:
    def test_pass_when_tests_actually_passed(self):
        """AI 聲稱通過且 exit_code=0 → 通過"""
        ctx = TaskContext(
            output="Running tests...\n5 passed in 2.3s",
            exit_code=0,
        )
        result = TestOutputVerifier().verify(ctx)
        assert result.passed is True

    def test_fabrication_detected(self):
        """AI 聲稱通過但 exit_code=1 → 捏造"""
        ctx = TaskContext(
            output="All tests passed successfully!\n✅ 10 tests passed",
            exit_code=1,
        )
        result = TestOutputVerifier().verify(ctx)
        assert result.passed is False
        assert "exit_code=1" in result.evidence

    def test_pass_when_no_test_claims(self):
        """輸出不含測試聲明 → 不適用，直接通過"""
        ctx = TaskContext(
            output="Refactored the module structure.",
            exit_code=0,
        )
        result = TestOutputVerifier().verify(ctx)
        assert result.passed is True

    def test_pass_when_claims_fail_and_exit_code_nonzero(self):
        """AI 聲稱失敗且 exit_code 也非零 → 一致，通過"""
        ctx = TaskContext(
            output="3 failed, 2 passed",
            exit_code=1,
        )
        result = TestOutputVerifier().verify(ctx)
        assert result.passed is True

    def test_verifier_name(self):
        assert TestOutputVerifier().name == "TestOutputVerifier"


# ════════════════════════════════════════
# VerifiedRegistry
# ════════════════════════════════════════

class TestVerifiedRegistry:
    def test_run_all_collects_results(self):
        registry = VerifiedRegistry()
        registry.register(TestOutputVerifier())
        ctx = TaskContext(output="5 passed", exit_code=0)
        results = registry.run_all(ctx)
        assert len(results) == 1
        assert results[0].passed is True

    def test_run_all_with_multiple_verifiers(self):
        registry = VerifiedRegistry()
        registry.register(TestOutputVerifier())
        registry.register(TestOutputVerifier())
        ctx = TaskContext(output="5 passed", exit_code=0)
        results = registry.run_all(ctx)
        assert len(results) == 2

    def test_run_all_handles_verifier_exception(self):
        class BrokenVerifier(BaseVerifier):
            @property
            def name(self) -> str:
                return "BrokenVerifier"

            def verify(self, ctx):
                raise RuntimeError("boom")

        registry = VerifiedRegistry()
        registry.register(BrokenVerifier())
        ctx = TaskContext()
        results = registry.run_all(ctx)
        assert len(results) == 1
        assert results[0].passed is False
        assert "exception" in results[0].evidence.lower()

    def test_verifiers_returns_copy(self):
        registry = VerifiedRegistry()
        registry.register(TestOutputVerifier())
        copy = registry.verifiers
        copy.clear()
        assert len(registry.verifiers) == 1  # 原始不受影響

    def test_default_registry(self):
        registry = create_default_registry()
        assert len(registry.verifiers) == 1
        assert registry.verifiers[0].name == "TestOutputVerifier"


# ════════════════════════════════════════
# VerificationHook 整合
# ════════════════════════════════════════

class TestVerificationHook:
    def test_integration_logs_warning_on_fabrication(self, caplog):
        """VerificationHook 偵測到捏造時應發出 warning"""
        hook = VerificationHook()
        ctx = TaskContext(
            output="All tests passed!",
            exit_code=1,
        )
        with caplog.at_level(logging.WARNING):
            hook.on_complete(ctx)
        assert any("FAILED" in r.message for r in caplog.records)

    def test_integration_no_warning_when_clean(self, caplog):
        """驗證通過時不應有 warning"""
        hook = VerificationHook()
        ctx = TaskContext(
            output="Refactored code, no tests.",
            exit_code=0,
        )
        with caplog.at_level(logging.WARNING):
            hook.on_complete(ctx)
        verification_warnings = [
            r for r in caplog.records if "Verification" in r.message
        ]
        assert len(verification_warnings) == 0

    def test_hook_in_worker_collect_hooks(self):
        """VerificationHook 應出現在 worker hook 列表"""
        from app.hooks import collect_hooks
        hooks = collect_hooks("worker")
        names = [type(h).__name__ for h in hooks]
        assert "VerificationHook" in names

    def test_hook_before_cleanup(self):
        """VerificationHook 應在 CleanupHook 之前"""
        from app.hooks import collect_hooks
        hooks = collect_hooks("worker")
        names = [type(h).__name__ for h in hooks]
        vh_idx = names.index("VerificationHook")
        ch_idx = names.index("CleanupHook")
        assert vh_idx < ch_idx

    def test_custom_registry(self):
        """可注入自訂 registry"""
        registry = VerifiedRegistry()
        hook = VerificationHook(registry=registry)
        ctx = TaskContext(output="whatever", exit_code=0)
        hook.on_complete(ctx)  # 空 registry 不拋例外
