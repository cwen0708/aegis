"""成本感知模型路由 — 根據卡片標籤與 prompt 複雜度自動選擇最經濟的模型。

優先順序：card.model > tag-based > prompt 提到模型 > max(complexity, member_model)

所有模型名稱和分數從 model_registry 取得，不在此 hardcode。
"""

import re
from typing import Optional

from app.core.model_registry import (
    get_tier, FAMILY_TIER, FAMILY_ALIASES,
    PROVIDER_FAILOVER, FAILOVER_DEFAULT_MODEL,
)

# Tag → 模型映射規則（按優先順序排列，第一個匹配即返回）
_TAG_RULES: list[tuple[set[str], str]] = [
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

# prompt 中可偵測的模型名稱（按 tier 高→低排序）
_PROMPT_MODEL_NAMES = sorted(FAMILY_TIER.keys(), key=lambda m: FAMILY_TIER[m], reverse=True)


def get_failover_chain(provider: str) -> list[str]:
    """回傳指定 provider 的備援 provider 列表。"""
    return PROVIDER_FAILOVER.get(provider, [])


def get_failover_model(provider: str) -> str:
    """回傳 failover provider 應使用的預設模型。"""
    return FAILOVER_DEFAULT_MODEL.get(provider, "")


def detect_model_mention(prompt: str) -> Optional[str]:
    """偵測 prompt 中是否直接提到模型名稱（用戶明確指定）。

    例如：「請用 opus 來分析」「use sonnet」「haiku 就好」「用 gemini-pro」
    按 tier 高→低檢查，優先匹配高階模型。
    """
    lower = prompt.lower()
    for model in _PROMPT_MODEL_NAMES:
        if model in lower:
            return model
    # 也檢查別名
    for alias, family in FAMILY_ALIASES.items():
        if alias in lower and alias not in FAMILY_TIER:
            return family
    return None


def assess_complexity(prompt: str) -> str:
    """根據 prompt 長度與內容評估複雜度，回傳建議模型等級。

    優先級：prompt 明確提到模型 > 關鍵字 > 長度
    """
    # prompt 直接提到模型名稱 → 尊重用戶意圖
    mentioned = detect_model_mention(prompt)
    if mentioned:
        return mentioned

    length = len(prompt)

    if _OPUS_KEYWORDS.search(prompt):
        return "opus"

    if length > 2000:
        return "opus"

    if _SONNET_KEYWORDS.search(prompt) or length >= 500:
        return "sonnet"

    return "haiku"


def resolve_model_by_tags(tags: list[str], default: Optional[str] = None) -> Optional[str]:
    """根據卡片 tags 解析模型。"""
    tag_set = set(tags)
    for trigger_tags, model in _TAG_RULES:
        if tag_set & trigger_tags:
            return model
    return default


def resolve_model(tags: list[str], prompt: str = "", default: Optional[str] = None,
                   member_model: Optional[str] = None) -> Optional[str]:
    """統一模型路由入口。

    優先級：tag-based > max(complexity-based, member_model) > default

    member_model 作為 floor（最低保障），complexity-based 只能往上升不能往下降。
    """
    # 1. Tag-based 路由（明確指定，最高優先）
    tag_result = resolve_model_by_tags(tags)
    if tag_result:
        return tag_result

    # 2. Complexity-based 路由（含 prompt 提到模型名稱偵測）
    if prompt:
        routed = assess_complexity(prompt)
        if member_model:
            routed_tier = get_tier(routed)
            member_tier = get_tier(member_model)
            # 未知模型（tier=-1）→ 尊重成員設定，不降級
            if member_tier < 0:
                return member_model
            return routed if routed_tier >= member_tier else member_model
        return routed

    return member_model or default
