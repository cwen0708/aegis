"""模型路由單元測試 — tag-based + complexity-based。"""

from app.core.model_router import (
    resolve_model_by_tags,
    assess_complexity,
    resolve_model,
    MODEL_TIER,
)


class TestResolveModelByTags:
    """resolve_model_by_tags 函式測試。"""

    def test_ai_opus_tag(self):
        assert resolve_model_by_tags(["AI-Opus"]) == "opus"

    def test_complex_tag(self):
        assert resolve_model_by_tags(["complex"]) == "opus"

    def test_ai_sonnet_tag(self):
        assert resolve_model_by_tags(["AI-Sonnet"]) == "sonnet"

    def test_ai_haiku_tag(self):
        assert resolve_model_by_tags(["AI-Haiku"]) == "haiku"

    def test_simple_tag(self):
        assert resolve_model_by_tags(["simple"]) == "haiku"

    def test_refactor_tag(self):
        assert resolve_model_by_tags(["Refactor"]) == "haiku"

    def test_no_matching_tag_returns_default(self):
        assert resolve_model_by_tags(["P0", "Feature"]) is None

    def test_no_matching_tag_returns_custom_default(self):
        assert resolve_model_by_tags(["P0"], default="sonnet") == "sonnet"

    def test_empty_tags(self):
        assert resolve_model_by_tags([]) is None

    def test_opus_priority_over_haiku(self):
        """AI-Opus 和 AI-Haiku 同時存在時，Opus 優先。"""
        assert resolve_model_by_tags(["AI-Haiku", "AI-Opus"]) == "opus"

    def test_opus_priority_over_sonnet(self):
        """AI-Opus 和 AI-Sonnet 同時存在時，Opus 優先。"""
        assert resolve_model_by_tags(["AI-Sonnet", "AI-Opus"]) == "opus"

    def test_sonnet_priority_over_haiku(self):
        """AI-Sonnet 和 AI-Haiku 同時存在時，Sonnet 優先。"""
        assert resolve_model_by_tags(["AI-Haiku", "AI-Sonnet"]) == "sonnet"

    def test_mixed_tags(self):
        """混合業務標籤和模型標籤。"""
        assert resolve_model_by_tags(["P0", "Cost", "AI-Haiku", "Feature"]) == "haiku"


class TestModelTier:
    """MODEL_TIER 常數驗證。"""

    def test_tier_ordering(self):
        assert MODEL_TIER["haiku"] < MODEL_TIER["sonnet"] < MODEL_TIER["opus"]

    def test_all_tiers_defined(self):
        assert set(MODEL_TIER.keys()) == {"haiku", "sonnet", "opus"}


class TestAssessComplexity:
    """assess_complexity 函式測試。"""

    def test_short_prompt_returns_haiku(self):
        assert assess_complexity("你好") == "haiku"

    def test_short_prompt_under_500(self):
        assert assess_complexity("請幫我看一下這個檔案") == "haiku"

    def test_medium_prompt_by_length(self):
        """500-2000 字元回傳 sonnet。"""
        prompt = "a" * 600
        assert assess_complexity(prompt) == "sonnet"

    def test_long_prompt_returns_opus(self):
        """超過 2000 字元回傳 opus。"""
        prompt = "a" * 2500
        assert assess_complexity(prompt) == "opus"

    def test_sonnet_keyword_in_short_prompt(self):
        """短 prompt 含程式碼修改關鍵字 → sonnet。"""
        assert assess_complexity("修改這個函式") == "sonnet"

    def test_sonnet_keyword_implement(self):
        assert assess_complexity("implement a new endpoint") == "sonnet"

    def test_opus_keyword_architecture(self):
        """含架構設計關鍵字 → opus，不論長度。"""
        assert assess_complexity("架構設計") == "opus"

    def test_opus_keyword_design_pattern(self):
        assert assess_complexity("design pattern for this module") == "opus"

    def test_opus_keyword_step_by_step(self):
        assert assess_complexity("step by step analysis") == "opus"

    def test_opus_keyword_tradeoff(self):
        assert assess_complexity("比較兩種方案的優缺點") == "opus"

    def test_opus_keyword_overrides_short_length(self):
        """即使是短 prompt，opus 關鍵字仍生效。"""
        assert assess_complexity("多步驟推理") == "opus"

    def test_empty_prompt(self):
        assert assess_complexity("") == "haiku"


class TestResolveModel:
    """resolve_model 統一入口測試。"""

    def test_tag_priority_over_complexity(self):
        """Tag-based 路由優先於 complexity-based。"""
        long_prompt = "a" * 3000  # 會被 assess_complexity 判為 opus
        assert resolve_model(["AI-Haiku"], long_prompt) == "haiku"

    def test_complexity_fallback_when_no_tag(self):
        """無匹配 tag 時，fallback 到 complexity-based。"""
        assert resolve_model(["P0", "Feature"], "修改這個函式") == "sonnet"

    def test_complexity_fallback_opus(self):
        long_prompt = "a" * 3000
        assert resolve_model([], long_prompt) == "opus"

    def test_complexity_fallback_haiku(self):
        assert resolve_model([], "你好") == "haiku"

    def test_default_when_no_prompt(self):
        """無 tag 無 prompt 時回傳 default。"""
        assert resolve_model([], "", default="sonnet") == "sonnet"

    def test_none_when_no_match_no_default(self):
        """無 tag 無 prompt 無 default → None。"""
        assert resolve_model([], "") is None

    def test_tag_with_empty_prompt_uses_tag(self):
        assert resolve_model(["AI-Opus"], "") == "opus"

    def test_mixed_tags_with_prompt(self):
        """有 tag 匹配時忽略 prompt 複雜度。"""
        assert resolve_model(["AI-Sonnet"], "架構設計很重要") == "sonnet"
