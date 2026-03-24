"""Tag-based 模型路由 — 根據卡片標籤自動選擇最經濟的模型。

優先順序：card.model > tag-based route > member-account > provider default
"""

from typing import Optional

# 模型成本等級（低 → 高）
MODEL_TIER = {
    "haiku": 1,
    "sonnet": 2,
    "opus": 3,
}

# Tag → 模型映射規則（按優先順序排列，第一個匹配即返回）
_TAG_RULES: list[tuple[set[str], str]] = [
    ({"AI-Opus", "complex"}, "opus"),
    ({"AI-Sonnet"}, "sonnet"),
    ({"AI-Haiku", "simple", "Refactor"}, "haiku"),
]


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
