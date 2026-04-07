"""成本感知模型路由 — 根據卡片標籤與 prompt 複雜度自動選擇最經濟的模型。

優先順序：card.model > tag-based route > complexity-based > member-account > provider default
"""

import re
from typing import Optional

# 模型成本等級（低 → 高）
MODEL_TIER = {
    "haiku": 1,
    "sonnet": 2,
    "opus": 3,
}

# Tag → 模型映射規則（按優先順序排列，第一個匹配即返回）
_TAG_RULES: list[tuple[set[str], str]] = [
    ({"M1", "ollama"}, "ollama"),       # Ollama 本地模型，優先級最高
    ({"M2", "openai"}, "openai"),        # OpenAI 模型
    ({"AI-Opus", "complex"}, "opus"),
    ({"AI-Sonnet"}, "sonnet"),
    ({"AI-Haiku", "simple", "Refactor"}, "haiku"),
]

# 複雜度偵測關鍵字
_OPUS_KEYWORDS = re.compile(
    r"架構設計|系統設計|設計模式|多步驟|分析並|重構整個|migration plan|architecture|design pattern|trade-?off|step.by.step|比較.*優缺點",
    re.IGNORECASE,
)
_SONNET_KEYWORDS = re.compile(
    r"修改|修正|新增功能|implement|refactor|bug\s*fix|程式碼|code review|寫一個|write a|update|add feature",
    re.IGNORECASE,
)


# Provider Failover Chain — 當某 provider 所有帳號都失敗時，依序嘗試的備援 provider
PROVIDER_FAILOVER: dict[str, list[str]] = {
    "claude": ["gemini", "openai"],
    "gemini": ["claude", "openai"],
    "openai": ["claude", "gemini"],
}

# 各 provider 的預設 failover 模型
_FAILOVER_DEFAULT_MODEL: dict[str, str] = {
    "claude": "sonnet",
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
}


def get_failover_chain(provider: str) -> list[str]:
    """回傳指定 provider 的備援 provider 列表。未知 provider 回傳空列表。"""
    return PROVIDER_FAILOVER.get(provider, [])


def get_failover_model(provider: str) -> str:
    """回傳 failover provider 應使用的預設模型。未知 provider 回傳空字串。"""
    return _FAILOVER_DEFAULT_MODEL.get(provider, "")


def assess_complexity(prompt: str) -> str:
    """根據 prompt 長度與內容評估複雜度，回傳建議模型等級。

    - 短 prompt（<500 字元）且無多步驟指標 → "haiku"
    - 中等 prompt（500-2000 字元）或含程式碼修改關鍵字 → "sonnet"
    - 長 prompt（>2000 字元）或含架構設計/多步驟推理關鍵字 → "opus"
    """
    length = len(prompt)

    # 關鍵字優先：opus 關鍵字不論長度都升級
    if _OPUS_KEYWORDS.search(prompt):
        return "opus"

    if length > 2000:
        return "opus"

    if _SONNET_KEYWORDS.search(prompt) or length >= 500:
        return "sonnet"

    return "haiku"


def resolve_model_by_tags(tags: list[str], default: Optional[str] = None) -> Optional[str]:
    """根據卡片 tags 解析模型。

    規則（按優先順序）：
    - tags 含 AI-Opus 或 complex → opus
    - tags 含 AI-Sonnet → sonnet
    - tags 含 AI-Haiku、simple 或 Refactor → haiku
    - 其他 → 回傳 default（不改變現有行為）
    """
    tag_set = set(tags)
    for trigger_tags, model in _TAG_RULES:
        if tag_set & trigger_tags:
            return model
    return default


def resolve_model(tags: list[str], prompt: str = "", default: Optional[str] = None) -> Optional[str]:
    """統一模型路由入口。

    優先級：tag-based > complexity-based > default
    """
    # 1. Tag-based 路由
    tag_result = resolve_model_by_tags(tags)
    if tag_result:
        return tag_result

    # 2. Complexity-based 路由（僅在有 prompt 時啟用）
    if prompt:
        return assess_complexity(prompt)

    return default
