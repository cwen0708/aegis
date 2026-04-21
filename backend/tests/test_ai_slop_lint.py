"""Tests for ai_slop_lint module.

TDD: 先寫測試再寫實作。
"""
from app.core.ai_slop_lint import SLOP_PATTERNS, SlopHit, check_slop


def test_hit_boilerplate():
    """典型 slop 句：應同時命中 'delves into' 與 'the realm of'。"""
    text = "This article delves into the realm of AI"
    hits = check_slop(text)

    matched_patterns = {hit.pattern for hit in hits}
    assert r"delves? into" in matched_patterns
    assert r"the realm of" in matched_patterns
    assert len(hits) >= 2


def test_original_ac_example():
    """原卡 AC：check_slop('This paper delves into the realm of') 至少命中 2 筆。"""
    hits = check_slop("This paper delves into the realm of")
    assert len(hits) >= 2


def test_clean_text_chinese():
    """正常中文描述應無命中。"""
    assert check_slop("修正任務卡的排程錯誤，並補上測試") == []


def test_clean_text_english():
    """正常英文描述應無命中。"""
    assert check_slop("Fix scheduler bug and add tests for the worker loop.") == []


def test_empty_text():
    """空字串回傳空 list。"""
    assert check_slop("") == []


def test_case_insensitive():
    """大小寫不敏感：DELVES INTO 也要命中。"""
    hits = check_slop("This paper DELVES INTO the topic")
    assert any(h.pattern == r"delves? into" for h in hits)
    # matched 保留原文大小寫
    assert any("DELVES INTO" in h.matched.upper() for h in hits)


def test_overlapping_patterns():
    """多個 pattern 重疊文本時，每個 pattern 都應獨立命中，不會互相吃掉。"""
    text = "state-of-the-art cutting-edge research"
    hits = check_slop(text)
    patterns_hit = {h.pattern for h in hits}
    assert r"state-of-the-art" in patterns_hit
    assert r"cutting-edge" in patterns_hit


def test_slop_hit_is_frozen():
    """SlopHit 必須是 frozen dataclass（符合 coding-style.md 不變性原則）。"""
    import dataclasses

    hit = SlopHit(pattern="x", matched="x", start=0, end=1)
    assert dataclasses.is_dataclass(hit)
    try:
        hit.start = 99  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("SlopHit should be frozen")


def test_hit_positions_are_correct():
    """start/end 索引應對應 text 中實際片段。"""
    text = "prefix delves into middle"
    hits = check_slop(text)
    target = next(h for h in hits if h.pattern == r"delves? into")
    assert text[target.start:target.end].lower() == "delves into"


def test_slop_patterns_is_tuple():
    """SLOP_PATTERNS 公開為不可變 tuple。"""
    assert isinstance(SLOP_PATTERNS, tuple)
    assert len(SLOP_PATTERNS) >= 10


def test_singular_plural_both_match():
    """delve/delves, pave/paves, play/plays 等單複數都要能命中。"""
    assert any(h.pattern == r"delves? into" for h in check_slop("she delve into X"))
    assert any(h.pattern == r"delves? into" for h in check_slop("she delves into X"))
    assert any(h.pattern == r"paves? the way" for h in check_slop("it pave the way"))
    assert any(h.pattern == r"paves? the way" for h in check_slop("it paves the way"))


def test_apostrophe_variants():
    """it's worth noting / its worth noting 都要能命中。"""
    assert check_slop("it's worth noting that X")
    assert check_slop("its worth noting that X")
