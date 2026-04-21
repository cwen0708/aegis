"""AI-slop Linter — 偵測 LLM 制式語氣 boilerplate。

來源：self-healing-autoresearch-metaclaw.md §1.9（_paper_writing.py:807-857）
用途：給卡片描述、PR 標題、commit message 等文本做檢查。

本 step 先提供純函式 API（無 IO、無全域副作用），尚未接任何 gate/hook。
後續 step 再評估包裝成 LintRule 整合 lint_rules.py。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 核心黑名單（step 1 先放 12 條，後續 step 2 再擴充到 40+）
# 原則：挑常見、誤判率低、明顯是 LLM 制式語氣的片語。
SLOP_PATTERNS: tuple[str, ...] = (
    r"delves? into",
    r"it'?s worth noting",
    r"plays? a crucial role",
    r"paves? the way",
    r"state-of-the-art",
    r"cutting-edge",
    r"a myriad of",
    r"bridge the gap",
    r"leverage the power of",
    r"the realm of",
    r"navigate the complexities",
    r"unlock the potential",
)


@dataclass(frozen=True)
class SlopHit:
    """命中的 slop 片段。

    Attributes:
        pattern: 命中的原始 regex pattern（SLOP_PATTERNS 中的字串）。
        matched: 實際命中的原文（保留大小寫）。
        start: 在 text 中的起始索引（含）。
        end: 結束索引（不含，符合 Python slicing 慣例）。
    """

    pattern: str
    matched: str
    start: int
    end: int


# 預先編譯，避免每次呼叫重新 compile；module-level 常數，不可變。
_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (pat, re.compile(pat, re.IGNORECASE)) for pat in SLOP_PATTERNS
)


def check_slop(text: str) -> list[SlopHit]:
    """回傳 text 內命中的所有 slop 片段（大小寫不敏感）。

    - 保持純函式：無 IO、無全域狀態修改。
    - 不阻擋也不丟例外，由 caller 決定如何處置。
    - 各 pattern 獨立掃描，重疊文本不會互相吃掉。

    Args:
        text: 要檢查的文本（卡片描述、PR 標題、commit message 等）。

    Returns:
        SlopHit 的新 list；無命中時回傳空 list。
    """
    if not text:
        return []

    hits: list[SlopHit] = []
    for pattern, compiled in _COMPILED:
        for match in compiled.finditer(text):
            hits.append(
                SlopHit(
                    pattern=pattern,
                    matched=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return hits
