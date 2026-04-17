"""
Anti-fabrication 驗證框架 — 防止 AI 成員產出捏造結果

提供：
- VerificationResult: 驗證結果 dataclass
- BaseVerifier: 驗證器抽象基底類
- TestOutputVerifier: 偵測測試結果捏造（聲稱通過但 exit_code 非零）
- VerifiedRegistry: 管理多個驗證器，統一執行
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.hooks import TaskContext

logger = logging.getLogger(__name__)

# 匹配常見的「測試通過」聲明
_PASS_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\d+)\s+passed", re.IGNORECASE),
    re.compile(r"all\s+(\d+\s+)?tests?\s+pass", re.IGNORECASE),
    re.compile(r"tests?\s+passed\s+successfully", re.IGNORECASE),
    re.compile(r"✅\s*.*test", re.IGNORECASE),
    re.compile(r"test.*\bpass(ed)?\b", re.IGNORECASE),
]

# 匹配「測試失敗」聲明
_FAIL_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\d+)\s+failed", re.IGNORECASE),
    re.compile(r"tests?\s+failed", re.IGNORECASE),
    re.compile(r"❌\s*.*test", re.IGNORECASE),
    re.compile(r"FAILED", re.IGNORECASE),
]


@dataclass(frozen=True)
class VerificationResult:
    """單一驗證器的結果"""
    passed: bool
    verifier_name: str
    evidence: str       # 找到的可疑內容
    details: str = ""   # 補充說明


class BaseVerifier(ABC):
    """驗證器抽象基底類"""

    @property
    @abstractmethod
    def name(self) -> str:
        """驗證器名稱"""

    @abstractmethod
    def verify(self, ctx: "TaskContext") -> VerificationResult:
        """執行驗證，回傳結果"""


class TestOutputVerifier(BaseVerifier):
    """偵測測試結果捏造 — AI 聲稱測試通過但 exit_code 非零"""

    @property
    def name(self) -> str:
        return "TestOutputVerifier"

    def verify(self, ctx: "TaskContext") -> VerificationResult:
        output = ctx.output
        exit_code = ctx.exit_code

        claims_pass = any(p.search(output) for p in _PASS_PATTERNS)
        claims_fail = any(p.search(output) for p in _FAIL_PATTERNS)

        # 情境 1: 聲稱通過但 exit_code 非零 → 捏造
        if claims_pass and not claims_fail and exit_code != 0:
            return VerificationResult(
                passed=False,
                verifier_name=self.name,
                evidence=f"Output claims tests passed but exit_code={exit_code}",
                details="AI 輸出聲稱測試通過，但實際執行結果為失敗",
            )

        # 情境 2: 聲稱失敗但 exit_code 為零 → 可疑但不嚴重，仍通過
        # 情境 3: 無測試相關聲明 → 不適用，直接通過
        return VerificationResult(
            passed=True,
            verifier_name=self.name,
            evidence="",
            details="測試聲明與 exit_code 一致" if claims_pass else "未偵測到測試相關聲明",
        )


class VerifiedRegistry:
    """管理驗證器集合，統一執行所有驗證"""

    def __init__(self) -> None:
        self._verifiers: list[BaseVerifier] = []

    def register(self, verifier: BaseVerifier) -> None:
        """註冊一個驗證器"""
        self._verifiers.append(verifier)

    @property
    def verifiers(self) -> list[BaseVerifier]:
        """取得已註冊的驗證器（唯讀副本）"""
        return list(self._verifiers)

    def run_all(self, ctx: "TaskContext") -> list[VerificationResult]:
        """依序執行所有驗證器，回傳結果列表"""
        results: list[VerificationResult] = []
        for verifier in self._verifiers:
            try:
                result = verifier.verify(ctx)
                results.append(result)
            except Exception as e:
                logger.warning(f"[Verification] {verifier.name} failed: {e}")
                results.append(VerificationResult(
                    passed=False,
                    verifier_name=verifier.name,
                    evidence=f"Verifier raised exception: {e}",
                    details="驗證器執行時發生錯誤",
                ))
        return results


def create_default_registry() -> VerifiedRegistry:
    """建立包含所有預設驗證器的 registry"""
    registry = VerifiedRegistry()
    registry.register(TestOutputVerifier())
    return registry
