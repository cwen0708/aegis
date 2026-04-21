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
    "gemini-2.5-flash":       ModelInfo("Gemini 2.5 Flash", "gemini-flash", "gemini", 1, 0.075, 0.3),
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
# Provider-Model 白名單（每家 AI CLI 能接受的 model 清單）
# ============================================================
# 目的：擋掉「把 OpenAI 的 o3 塞給 Claude CLI」這類跨家錯配。
# 每個 provider 列出它能接受的完整 model id + CLI 短別名。
PROVIDER_MODEL_MATRIX: dict[str, frozenset[str]] = {
    "claude": frozenset({
        # 完整 id
        "claude-opus-4-6", "claude-opus-4",
        "claude-sonnet-4-6", "claude-sonnet-4", "claude-sonnet-3-5",
        "claude-haiku-4-5", "claude-haiku-3",
        # Claude CLI 短別名（--model opus / sonnet / haiku）
        "opus", "sonnet", "haiku",
    }),
    "gemini": frozenset({
        "gemini-2.5-pro-preview", "gemini-2.0-flash",
        "gemini-1.5-pro", "gemini-3.1-pro-preview",
        "gemini-flash", "gemini-2.5-flash",
    }),
    "openai": frozenset({
        "gpt-4o", "gpt-4o-mini", "o3",
    }),
    "ollama": frozenset({
        "llama3.1:8b", "llama3.1:70b", "llama3:8b",
    }),
}


class IncompatibleModelError(ValueError):
    """Model 不屬於指定 provider 的合法清單。配置錯誤，不應 retry。"""

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        allowed = sorted(PROVIDER_MODEL_MATRIX.get(provider, frozenset()))
        super().__init__(
            f"Model '{model}' is not allowed for provider '{provider}'. "
            f"Allowed: {allowed}"
        )


def validate_provider_model(provider: str, model: str) -> None:
    """檢查 (provider, model) 配對是否合法。

    - 空 model 視為合法（讓 cmd builder 套用自己的預設）
    - 未知 provider 視為合法（不擋自訂 provider）
    - 不合法 → raise IncompatibleModelError
    """
    if not model:
        return
    allowed = PROVIDER_MODEL_MATRIX.get(provider)
    if allowed is None:
        return
    if model not in allowed:
        raise IncompatibleModelError(provider, model)


def list_models_by_provider(provider: str) -> list[str]:
    """回傳 provider 的合法 model 清單（sorted）。未知 provider 回傳空 list。"""
    return sorted(PROVIDER_MODEL_MATRIX.get(provider, frozenset()))


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


# Claude CLI 用短別名（opus/sonnet/haiku），其他 provider 用完整 id
_CLAUDE_TIER_ALIAS: dict[int, str] = {3: "opus", 2: "sonnet", 1: "haiku"}


def resolve_model_for_provider_tier(provider: str, tier: int) -> str:
    """依 (provider, tier) 找最合適的 model。

    用途：跨 provider 的 tier-aware 模型映射。當 member 有多個不同 provider 的
    帳號（e.g. claude + gemini + openai），路由決定了「tier 3」之後，每家 provider
    應該用自己家對應 tier 的 model，而不是共用某一家的短名。

    - Claude 回短別名（opus/sonnet/haiku），Claude CLI 接受。
    - 其他 provider 回該 provider + tier 的第一個完整 model id（sorted 取 deterministic）。
    - Tier 不對應時 fallback 到 provider 的 task 預設。
    - 未知 provider 回空字串。
    """
    if provider == "claude":
        return _CLAUDE_TIER_ALIAS.get(tier, "sonnet")
    candidates = sorted(
        m_id for m_id, info in MODELS.items()
        if info.provider == provider and info.tier == tier
    )
    if candidates:
        return candidates[0]
    # Tier 無對應，fallback 到 task 預設
    return PROVIDER_DEFAULTS.get((provider, "task"), "")
