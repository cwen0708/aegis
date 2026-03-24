"""Tag-based 模型路由單元測試。"""

from app.core.model_router import resolve_model_by_tags, MODEL_TIER


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
