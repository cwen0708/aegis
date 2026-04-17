"""集中的模型註冊表 — 所有模型名稱、分數、價格、別名都在這裡。

其他模組應從這裡 import，不要各自 hardcode 模型名稱。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelInfo:
    """模型資訊"""
    name: str           # 顯示名稱（如 "Claude Opus 4.6"）
    family: str         # 家族短名（如 "opus", "sonnet", "haiku"）
    provider: str       # 提供商（"claude", "gemini", "openai"）
    tier: int           # 能力等級（1=經濟, 2=標準, 3=旗艦）
    input_cost: float   # 每 1M input tokens 美元
    output_cost: float  # 每 1M output tokens 美元


# ============================================================
# 模型註冊表（唯一真相來源）
# ============================================================
MODELS: dict[str, ModelInfo] = {
    # --- Claude ---
    "claude-opus-4-6":    ModelInfo("Claude Opus 4.6",   "opus",   "claude", 3, 15.0,  75.0),
    "claude-opus-4":      ModelInfo("Claude Opus 4",     "opus",   "claude", 3, 15.0,  75.0),
    "claude-sonnet-4-6":  ModelInfo("Claude Sonnet 4.6", "sonnet", "claude", 2,  3.0,  15.0),
    "claude-sonnet-4":    ModelInfo("Claude Sonnet 4",   "sonnet", "claude", 2,  3.0,  15.0),
    "claude-sonnet-3-5":  ModelInfo("Claude Sonnet 3.5", "sonnet", "claude", 2,  3.0,  15.0),
    "claude-haiku-4-5":   ModelInfo("Claude Haiku 4.5",  "haiku",  "claude", 1,  0.8,   4.0),
    "claude-haiku-3":     ModelInfo("Claude Haiku 3",    "haiku",  "claude", 1,  0.8,   4.0),
    # --- Gemini ---
    "gemini-2.5-pro-preview": ModelInfo("Gemini 2.5 Pro",  "gemini-pro",   "gemini", 3, 1.25, 10.0),
    "gemini-2.0-flash":       ModelInfo("Gemini 2.0 Flash", "gemini-flash", "gemini", 1, 0.075, 0.3),
    "gemini-1.5-pro":         ModelInfo("Gemini 1.5 Pro",  "gemini-pro",   "gemini", 2, 1.25,  5.0),
    "gemini-3.1-pro-preview": ModelInfo("Gemini 3.1 Pro",  "gemini-pro",   "gemini", 2, 1.25,  5.0),
    "gemini-flash":           ModelInfo("Gemini Flash",    "gemini-flash", "gemini", 1, 0.075, 0.3),
    # --- OpenAI ---
    "gpt-4o":      ModelInfo("GPT-4o",      "gpt-4o",      "openai", 2, 2.5,  10.0),
    "gpt-4o-mini": ModelInfo("GPT-4o Mini", "gpt-4o-mini", "openai", 1, 0.15,  0.6),
    "o3":          ModelInfo("o3",          "o3",          "openai", 3, 10.0,  40.0),
}

# 短名（family）→ tier 對照（給 model_router 用）
# 從 MODELS 自動生成，取每個 family 的最高 tier
FAMILY_TIER: dict[str, int] = {}
for _info in MODELS.values():
    existing = FAMILY_TIER.get(_info.family, 0)
    if _info.tier > existing:
        FAMILY_TIER[_info.family] = _info.tier

# 短名別名（用戶可能用的縮寫）
FAMILY_ALIASES: dict[str, str] = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
    "flash": "gemini-flash",
    "gemini-flash": "gemini-flash",
    "gemini-pro": "gemini-pro",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "o3": "o3",
}

# Provider 預設模型（按場景）
PROVIDER_DEFAULTS: dict[tuple[str, str], str] = {
    ("claude", "chat"): "haiku",
    ("claude", "task"): "sonnet",
    ("gemini", "chat"): "gemini-flash",
    ("gemini", "task"): "gemini-3.1-pro-preview",
    ("openai", "chat"): "gpt-4o-mini",
    ("openai", "task"): "gpt-4o",
}

# Provider failover chain
PROVIDER_FAILOVER: dict[str, list[str]] = {
    "claude": ["gemini", "openai"],
    "gemini": ["claude", "openai"],
    "openai": ["claude", "gemini"],
}

FAILOVER_DEFAULT_MODEL: dict[str, str] = {
    "claude": "sonnet",
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
}


# ============================================================
# 工具函式
# ============================================================

def get_tier(model_name: str) -> int:
    """取得模型的能力等級。支援完整名稱和短名。

    回傳 -1 表示未知模型。
    """
    # 先查完整名稱
    info = MODELS.get(model_name)
    if info:
        return info.tier
    # 再查短名
    return FAMILY_TIER.get(model_name, FAMILY_TIER.get(FAMILY_ALIASES.get(model_name, ""), -1))


def get_family(model_id: str) -> str:
    """從完整 model ID 提取家族短名。

    "claude-opus-4-6" → "opus"
    "gemini-2.0-flash" → "gemini-flash"
    "unknown-model" → "unknown"
    """
    info = MODELS.get(model_id)
    if info:
        return info.family
    # Fallback: 關鍵字匹配
    s = model_id.lower()
    if "opus" in s:
        return "opus"
    if "sonnet" in s:
        return "sonnet"
    if "haiku" in s:
        return "haiku"
    if "flash" in s:
        return "gemini-flash"
    if "gemini" in s and "pro" in s:
        return "gemini-pro"
    if "gpt" in s:
        return model_id
    return "unknown"


def get_pricing(model_id: str) -> tuple[float, float]:
    """取得 (input_cost, output_cost) per 1M tokens。未知模型回傳 haiku 價格。"""
    info = MODELS.get(model_id)
    if info:
        return (info.input_cost, info.output_cost)
    # Fallback: 用 family 找
    family = get_family(model_id)
    for m in MODELS.values():
        if m.family == family:
            return (m.input_cost, m.output_cost)
    return (0.8, 4.0)  # 預設 haiku


def get_provider_default(provider: str, mode: str = "task") -> str:
    """取得 provider 在指定場景的預設模型。"""
    return PROVIDER_DEFAULTS.get((provider, mode), "")
