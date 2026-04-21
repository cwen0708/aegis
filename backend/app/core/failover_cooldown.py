"""Failover Cooldown — LLM provider key 層級的錯誤細分類與冷卻計算。

對應卡片 #13106 P1-SH-14 步驟 1。本模組只提供純函式與 immutable
資料結構，不觸碰 model_router / watchdog / error_classifier。

與 error_classifier.ErrorCategory 的差異：
- ErrorCategory 是 Worker retry 用的粗分類（api_error 涵蓋一切外部錯誤）
- FailoverErrorKind 是 provider key 層級細分類，用來決定冷卻長度
  （rate_limit / billing / auth / model_not_found 的處置截然不同）

後續步驟會把這些純函式整合進 model_router 的 failover chain。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class FailoverErrorKind(str, Enum):
    rate_limit = "rate_limit"
    billing = "billing"
    auth = "auth"
    model_not_found = "model_not_found"
    other = "other"


@dataclass(frozen=True)
class FailoverKeyState:
    """單一 provider key 的 failover 狀態（immutable）。

    更新時請用 ``dataclasses.replace(state, failures=state.failures + 1)``
    取得新物件，切勿嘗試 in-place mutation。
    """
    failures: int = 0
    last_failure_at: float = 0.0
    cooldown_until: float = 0.0


# 分類優先序：先比對較具體的 billing / auth / model_not_found，
# 再 fallback 到 rate_limit（因為 "quota exceeded" 會同時命中 rate_limit 與
# billing 的 "quota"，這裡的設計依卡片明文：quota exceeded → rate_limit）。
_PATTERNS: List[Tuple[re.Pattern, FailoverErrorKind]] = [
    (re.compile(r"429|rate[\s_-]?limit|too many requests|quota exceeded", re.IGNORECASE),
     FailoverErrorKind.rate_limit),
    (re.compile(r"insufficient_quota|billing|payment|credit", re.IGNORECASE),
     FailoverErrorKind.billing),
    (re.compile(r"401|unauthorized|invalid api key|authentication", re.IGNORECASE),
     FailoverErrorKind.auth),
    (re.compile(r"404|model not found|unknown model", re.IGNORECASE),
     FailoverErrorKind.model_not_found),
]


def classify_failover_error(msg: str) -> FailoverErrorKind:
    """根據錯誤訊息分類為 FailoverErrorKind。未命中時回 ``other``。"""
    if not msg:
        return FailoverErrorKind.other
    for pattern, kind in _PATTERNS:
        if pattern.search(msg):
            return kind
    return FailoverErrorKind.other


# (base, cap) for exponential formulas: base * 5 ** (failures - 1)，clamp 到 cap
_EXPONENTIAL_PARAMS = {
    FailoverErrorKind.rate_limit: (60, 3600),
    FailoverErrorKind.billing: (18000, 86400),
    FailoverErrorKind.other: (60, 3600),
}

_AUTH_FIXED_COOLDOWN = 3600
_MODEL_NOT_FOUND_COOLDOWN = 0


def compute_cooldown(kind: FailoverErrorKind, failures: int) -> float:
    """依錯誤種類與累積失敗次數計算冷卻秒數。

    - rate_limit / other：base=60, cap=3600，公式 ``base * 5 ** (failures - 1)``
    - billing：base=18000, cap=86400，同指數公式
    - auth：固定 3600 秒
    - model_not_found：0（不進冷卻，直接跳過該 key）
    """
    if kind is FailoverErrorKind.auth:
        return float(_AUTH_FIXED_COOLDOWN)
    if kind is FailoverErrorKind.model_not_found:
        return float(_MODEL_NOT_FOUND_COOLDOWN)

    base, cap = _EXPONENTIAL_PARAMS[kind]
    # failures 保守地至少當 1 算，避免 5 ** -1 產生分數
    exponent = max(failures - 1, 0)
    value = base * (5 ** exponent)
    return float(min(value, cap))
