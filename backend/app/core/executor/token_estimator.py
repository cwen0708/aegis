"""
Token Estimator — Context Budget 估算模組

粗估 prompt token 數（char / 4），判斷是否需要 compaction。
屬於 Context Rot 防護（Harness E3）Step 1。
"""

from __future__ import annotations

from dataclasses import dataclass

# 各模型的 context window 上限（單位：token）
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-sonnet": 200_000,
    "claude-opus": 200_000,
    "claude-haiku": 200_000,
    "gemini": 1_000_000,
    "gemini-pro": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4": 128_000,
}

_DEFAULT_CONTEXT_LIMIT = 200_000

_COMPACTION_THRESHOLD = 0.6


@dataclass(frozen=True)
class ContextBudget:
    """某次 prompt 的 context 使用狀況快照。"""

    model_limit: int
    estimated_used: int
    remaining: int
    usage_pct: float
    needs_compaction: bool


def estimate_tokens(text: str) -> int:
    """粗估 token 數：len(text) / 4，無外部依賴。"""
    return len(text) // 4


def check_context_budget(prompt_text: str, model: str) -> ContextBudget:
    """計算 prompt 對指定模型的 context 使用狀況。

    Parameters
    ----------
    prompt_text:
        完整 prompt 文字。
    model:
        模型識別字串，對應 MODEL_CONTEXT_LIMITS 的 key。
        未知模型會 fallback 到預設上限。

    Returns
    -------
    ContextBudget
        包含使用率與是否需要 compaction 的判斷。
    """
    model_limit = MODEL_CONTEXT_LIMITS.get(model, _DEFAULT_CONTEXT_LIMIT)
    estimated_used = estimate_tokens(prompt_text)
    remaining = max(model_limit - estimated_used, 0)
    usage_pct = estimated_used / model_limit if model_limit > 0 else 1.0
    needs_compaction = usage_pct > _COMPACTION_THRESHOLD

    return ContextBudget(
        model_limit=model_limit,
        estimated_used=estimated_used,
        remaining=remaining,
        usage_pct=usage_pct,
        needs_compaction=needs_compaction,
    )
