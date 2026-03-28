"""
成本追蹤計算模塊 — 根據 model 和 token 數計算 API 費用
"""
import logging

logger = logging.getLogger(__name__)

# Claude 定價（per 1M tokens，2026-03-28）
CLAUDE_PRICING = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},  # $15/$75 per 1M
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},  # $3/$15 per 1M
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-sonnet-3-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0},  # $0.80/$4 per 1M
    "claude-haiku-3": {"input": 0.8, "output": 4.0},
}

# Gemini 定價（估計）
GEMINI_PRICING = {
    "gemini-2.0-flash": {"input": 0.075, "output": 0.3},  # per 1K tokens
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},  # per 1M tokens
}


def extract_model_family(model_str: str) -> str:
    """從完整 model 名稱提取家族名稱（如 'haiku', 'sonnet', 'opus'）"""
    if not model_str:
        return "haiku"

    s = model_str.lower()
    if "opus" in s:
        return "opus"
    elif "sonnet" in s:
        return "sonnet"
    elif "haiku" in s:
        return "haiku"
    elif "gemini" in s:
        return "gemini"
    return "haiku"  # 預設


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """計算 API 費用（USD）

    Args:
        model: 完整 model 名稱或家族名稱
        input_tokens: 輸入 token 數
        output_tokens: 輸出 token 數

    Returns:
        預估費用（USD）
    """
    if input_tokens < 0 or output_tokens < 0:
        return 0.0

    if not model:
        # Fallback to Haiku if model is not specified
        model = "claude-haiku-4-5"

    model_key = model.lower()

    # 精確匹配
    if model_key in CLAUDE_PRICING:
        pricing = CLAUDE_PRICING[model_key]
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    # 根據家族名稱匹配
    family = extract_model_family(model)

    for key, pricing in CLAUDE_PRICING.items():
        if family in key:
            input_cost = (input_tokens / 1_000_000) * pricing["input"]
            output_cost = (output_tokens / 1_000_000) * pricing["output"]
            return input_cost + output_cost

    for key, pricing in GEMINI_PRICING.items():
        if family in key:
            # Gemini 按 1K tokens 計費
            input_cost = (input_tokens / 1000) * pricing["input"]
            output_cost = (output_tokens / 1000) * pricing["output"]
            return input_cost + output_cost

    logger.warning(f"Unknown model for cost calculation: {model}, defaulting to Haiku")
    pricing = CLAUDE_PRICING.get("claude-haiku-4-5", {"input": 0.8, "output": 4.0})
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
