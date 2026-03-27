"""
Error Classifier — 根據輸出與 exit code 判斷錯誤類型

用於 Worker retry 邏輯，決定失敗任務是否值得重試。
"""
import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple


class ErrorCategory(str, Enum):
    dependency_missing = "dependency_missing"
    syntax_error = "syntax_error"
    test_failure = "test_failure"
    api_error = "api_error"
    permission_denied = "permission_denied"
    timeout = "timeout"
    resource_limit = "resource_limit"
    unknown = "unknown"


@dataclass
class ErrorClassification:
    category: ErrorCategory
    retryable: bool
    confidence: float
    suggested_action: str
    matched_pattern: str


# (pattern, category, retryable, confidence, suggested_action)
_PATTERNS: List[Tuple[re.Pattern, ErrorCategory, bool, float, str]] = [
    # Dependency / Import
    (re.compile(r"ModuleNotFoundError:\s*No module named\s+'([^']+)'"),
     ErrorCategory.dependency_missing, False, 0.95,
     "安裝缺少的套件後重試"),
    (re.compile(r"ImportError:\s*cannot import name"),
     ErrorCategory.dependency_missing, False, 0.90,
     "檢查套件版本或導入路徑"),
    (re.compile(r"ImportError:\s*No module named"),
     ErrorCategory.dependency_missing, False, 0.90,
     "安裝缺少的套件後重試"),

    # Syntax
    (re.compile(r"SyntaxError:\s*"),
     ErrorCategory.syntax_error, False, 0.95,
     "修正語法錯誤後重試"),
    (re.compile(r"IndentationError:\s*"),
     ErrorCategory.syntax_error, False, 0.95,
     "修正縮排錯誤後重試"),

    # Test failure
    (re.compile(r"FAILED\s+tests?/"),
     ErrorCategory.test_failure, False, 0.85,
     "檢查失敗的測試案例並修正"),
    (re.compile(r"AssertionError|AssertionError|assert\s+.*==.*"),
     ErrorCategory.test_failure, False, 0.70,
     "檢查斷言邏輯"),
    (re.compile(r"\d+\s+failed.*passed|passed.*\d+\s+failed"),
     ErrorCategory.test_failure, False, 0.90,
     "檢查失敗的測試案例並修正"),

    # API / Rate limit
    (re.compile(r"rate[\s_-]?limit|429|too many requests", re.IGNORECASE),
     ErrorCategory.api_error, True, 0.85,
     "等待 rate limit 冷卻後重試"),
    (re.compile(r"api[\s_-]?error|APIError|APIConnectionError", re.IGNORECASE),
     ErrorCategory.api_error, True, 0.80,
     "API 連線問題，可重試"),
    (re.compile(r"500\s+Internal Server Error|502\s+Bad Gateway|503\s+Service Unavailable"),
     ErrorCategory.api_error, True, 0.80,
     "伺服器端錯誤，可重試"),

    # Permission
    (re.compile(r"PermissionError:\s*"),
     ErrorCategory.permission_denied, False, 0.95,
     "檢查檔案或目錄權限"),
    (re.compile(r"Permission denied|EACCES", re.IGNORECASE),
     ErrorCategory.permission_denied, False, 0.85,
     "檢查存取權限"),

    # Timeout
    (re.compile(r"TimeoutError|timed?\s*out|ETIMEDOUT", re.IGNORECASE),
     ErrorCategory.timeout, True, 0.85,
     "執行超時，可重試或調整超時設定"),

    # Resource limit
    (re.compile(r"MemoryError|OOM|Out of memory|Cannot allocate memory", re.IGNORECASE),
     ErrorCategory.resource_limit, False, 0.90,
     "記憶體不足，請減少資源用量"),
    (re.compile(r"No space left on device|ENOSPC", re.IGNORECASE),
     ErrorCategory.resource_limit, False, 0.90,
     "磁碟空間不足，請清理後重試"),
]


def classify_error(output: str, exit_code: int = 1) -> ErrorClassification:
    """根據錯誤輸出和 exit code 分類錯誤。

    Args:
        output: 任務的 stdout/stderr 輸出
        exit_code: 程序結束碼

    Returns:
        ErrorClassification 包含分類結果與建議動作
    """
    if not output:
        return ErrorClassification(
            category=ErrorCategory.unknown,
            retryable=True,
            confidence=0.1,
            suggested_action="無輸出可分析，保守重試",
            matched_pattern="",
        )

    for pattern, category, retryable, confidence, action in _PATTERNS:
        match = pattern.search(output)
        if match:
            return ErrorClassification(
                category=category,
                retryable=retryable,
                confidence=confidence,
                suggested_action=action,
                matched_pattern=match.group(0),
            )

    # 未匹配 — 保持向後相容，允許重試
    return ErrorClassification(
        category=ErrorCategory.unknown,
        retryable=True,
        confidence=0.1,
        suggested_action="未識別的錯誤類型，保守重試",
        matched_pattern="",
    )
