"""模型路由單元測試 — tag-based + complexity-based + provider failover。"""

import pytest

from app.core.model_router import (
    resolve_model_by_tags,
    assess_complexity,
    resolve_model,
    detect_model_mention,
    PROVIDER_FAILOVER,
    get_failover_chain,
    get_failover_model,
)
from app.core.model_registry import (
    FAMILY_TIER as MODEL_TIER,
    IncompatibleModelError,
    PROVIDER_MODEL_MATRIX,
    list_models_by_provider,
    resolve_model_for_provider_tier,
    validate_provider_model,
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

    def test_m1_tag_returns_ollama(self):
        """M1 標籤 → ollama 本地模型。"""
        assert resolve_model_by_tags(["M1"]) == "ollama"

    def test_ollama_tag_returns_ollama(self):
        """ollama 標籤 → ollama 本地模型。"""
        assert resolve_model_by_tags(["ollama"]) == "ollama"

    def test_ollama_priority_over_opus(self):
        """ollama/M1 規則優先級高於 AI-Opus。"""
        assert resolve_model_by_tags(["M1", "AI-Opus"]) == "ollama"

    def test_m2_tag_returns_openai(self):
        """M2 標籤 → openai。"""
        assert resolve_model_by_tags(["M2"]) == "openai"

    def test_openai_tag_returns_openai(self):
        """openai 標籤 → openai。"""
        assert resolve_model_by_tags(["openai"]) == "openai"

    def test_openai_priority_over_opus(self):
        """openai 規則優先級高於 AI-Opus。"""
        assert resolve_model_by_tags(["M2", "AI-Opus"]) == "openai"

    def test_ollama_priority_over_openai(self):
        """ollama 規則優先級高於 openai。"""
        assert resolve_model_by_tags(["M1", "M2"]) == "ollama"


class TestModelTier:
    """MODEL_TIER 常數驗證。"""

    def test_tier_ordering(self):
        assert MODEL_TIER["haiku"] < MODEL_TIER["sonnet"] < MODEL_TIER["opus"]

    def test_all_tiers_defined(self):
        # FAMILY_TIER 包含其他 provider（gemini/gpt 等），這裡只驗證 Claude 三層存在
        assert {"haiku", "sonnet", "opus"} <= set(MODEL_TIER.keys())


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


class TestProviderFailover:
    """Provider Failover Chain 測試。"""

    def test_claude_failover_chain(self):
        assert get_failover_chain("claude") == ["gemini", "openai"]

    def test_gemini_failover_chain(self):
        assert get_failover_chain("gemini") == ["claude", "openai"]

    def test_openai_failover_chain(self):
        assert get_failover_chain("openai") == ["claude", "gemini"]

    def test_unknown_provider_returns_empty(self):
        assert get_failover_chain("unknown") == []

    def test_failover_model_claude(self):
        assert get_failover_model("claude") == "sonnet"

    def test_failover_model_gemini(self):
        assert get_failover_model("gemini") == "gemini-2.0-flash"

    def test_failover_model_openai(self):
        assert get_failover_model("openai") == "gpt-4o-mini"

    def test_failover_model_unknown_returns_empty(self):
        assert get_failover_model("unknown") == ""

    def test_failover_dict_has_all_providers(self):
        assert set(PROVIDER_FAILOVER.keys()) == {"claude", "gemini", "openai"}

    def test_no_self_reference_in_chain(self):
        """每個 provider 的 failover chain 不包含自己。"""
        for provider, chain in PROVIDER_FAILOVER.items():
            assert provider not in chain

    def test_provider_failover_claude_to_openai_to_ollama(self):
        """Claude → OpenAI → Ollama 降級鏈驗證：每個 provider 都有備援。"""
        chain = get_failover_chain("claude")
        assert "openai" in chain
        # OpenAI 也有備援
        openai_chain = get_failover_chain("openai")
        assert len(openai_chain) > 0
        # 所有 provider 都有 failover model
        for p in ["claude", "openai", "gemini"]:
            assert get_failover_model(p) != ""


class TestDetectModelMention:
    """detect_model_mention 回歸測試 — 階段 0+ 救火（substring 誤判根因修復）。"""

    def test_tdengine_uuid_does_not_trigger(self) -> None:
        """根因回歸：TDEngine 設備表名 `inv_O6_jXHT7o3gbYvmgbyZ_90` 的 `o3`
        substring 不應被當成「用戶指定 o3 model」。"""
        assert detect_model_mention("inv_O6_jXHT7o3gbYvmgbyZ_90") is None

    def test_real_tdengine_row_does_not_trigger(self) -> None:
        """真實 cron 30 prompt 片段回歸：整行 TDEngine 表欄位說明不觸發。"""
        prompt = "INV 01 | inv_O6_jXHT7o3gbYvmgbyZ_90 | ts, power, daily_energy"
        assert detect_model_mention(prompt) is None

    def test_explicit_chinese_prefix_triggers(self) -> None:
        """自然語言「請用 opus」應觸發 opus。"""
        assert detect_model_mention("請用 opus 來分析") == "opus"

    def test_explicit_english_prefix_triggers(self) -> None:
        """英文「use sonnet」應觸發 sonnet。"""
        assert detect_model_mention("use sonnet") == "sonnet"

    def test_cli_style_prefix_triggers(self) -> None:
        """工具型前綴「--model opus」應觸發 opus。"""
        assert detect_model_mention("--model opus 執行") == "opus"

    def test_o3_with_cli_prefix_triggers(self) -> None:
        """明確 `--model o3` 仍應觸發（OpenAI 合法 model，由 validate 層決定能否用）。"""
        assert detect_model_mention("--model o3 執行") == "o3"

    def test_model_colon_prefix_triggers(self) -> None:
        """`model: xxx` 前綴應觸發。"""
        assert detect_model_mention("model: gemini-pro") == "gemini-pro"

    def test_first_prefix_with_invalid_candidate_falls_through(self) -> None:
        """第一個前綴匹配的 candidate 不是合法 family，應繼續找下一個匹配。

        例：`"model: inv_XXX use opus"` — `model:` 抓到 inv_XXX 不合法，
        `use` 抓到 opus 合法，回傳 opus。
        """
        assert detect_model_mention("model: inv_XXXo3YYY use opus") == "opus"

    def test_empty_prompt_returns_none(self) -> None:
        assert detect_model_mention("") is None

    def test_no_prefix_substring_ignored(self) -> None:
        """單純提到 opus 字樣但沒前綴詞不觸發（嚴格策略）。"""
        assert detect_model_mention("haiku 就好") is None


class TestValidateProviderModel:
    """validate_provider_model + PROVIDER_MODEL_MATRIX 測試。"""

    def test_o3_blocked_on_claude(self) -> None:
        """根因回歸：o3 是 OpenAI model，塞給 claude 必須 raise。"""
        with pytest.raises(IncompatibleModelError) as exc:
            validate_provider_model("claude", "o3")
        assert exc.value.provider == "claude"
        assert exc.value.model == "o3"

    def test_o3_allowed_on_openai(self) -> None:
        """o3 在 OpenAI 是合法 model，應放行。"""
        validate_provider_model("openai", "o3")  # should not raise

    def test_claude_full_ids_allowed(self) -> None:
        for model in ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]:
            validate_provider_model("claude", model)

    def test_claude_cli_aliases_allowed(self) -> None:
        """Claude CLI 短別名 opus/sonnet/haiku 也必須放行。"""
        for alias in ["opus", "sonnet", "haiku"]:
            validate_provider_model("claude", alias)

    def test_gemini_models_allowed(self) -> None:
        for model in ["gemini-2.0-flash", "gemini-2.5-pro-preview", "gemini-flash"]:
            validate_provider_model("gemini", model)

    def test_empty_model_passes(self) -> None:
        """空 model 代表「讓 cmd builder 套預設」，必須放行。"""
        validate_provider_model("claude", "")
        validate_provider_model("openai", "")

    def test_unknown_provider_passes(self) -> None:
        """未知 provider 不擋（給自訂 provider 留彈性）。"""
        validate_provider_model("some-custom-provider", "some-model")

    def test_claude_model_on_gemini_blocked(self) -> None:
        """跨家錯配：claude model 塞給 gemini 必須擋。"""
        with pytest.raises(IncompatibleModelError):
            validate_provider_model("gemini", "claude-opus-4-6")

    def test_gemini_model_on_openai_blocked(self) -> None:
        with pytest.raises(IncompatibleModelError):
            validate_provider_model("openai", "gemini-2.0-flash")

    def test_list_models_by_provider_sorted(self) -> None:
        """list_models_by_provider 回傳 sorted list。"""
        claude_models = list_models_by_provider("claude")
        assert claude_models == sorted(claude_models)
        assert "opus" in claude_models
        assert "o3" not in claude_models  # o3 不屬於 claude

    def test_list_models_by_provider_unknown(self) -> None:
        assert list_models_by_provider("nonexistent") == []

    def test_matrix_no_overlap_between_providers(self) -> None:
        """健全性檢查：各 provider 的 model 白名單不應該互相覆蓋
        （否則 validate 會同時允許 claude 的 'o3' 跟 openai 的 'o3'）。"""
        claude_set = PROVIDER_MODEL_MATRIX["claude"]
        openai_set = PROVIDER_MODEL_MATRIX["openai"]
        gemini_set = PROVIDER_MODEL_MATRIX["gemini"]
        assert claude_set.isdisjoint(openai_set), "claude vs openai 有重疊"
        assert claude_set.isdisjoint(gemini_set), "claude vs gemini 有重疊"
        assert openai_set.isdisjoint(gemini_set), "openai vs gemini 有重疊"

    def test_error_message_contains_allowed_list(self) -> None:
        """錯誤訊息應列出該 provider 的合法 model，方便 debug。"""
        with pytest.raises(IncompatibleModelError) as exc:
            validate_provider_model("claude", "gpt-5-turbo")
        assert "opus" in str(exc.value)
        assert "gpt-5-turbo" in str(exc.value)


class TestResolveModelForProviderTier:
    """resolve_model_for_provider_tier — 跨 provider tier-aware 映射。

    回歸 worker.py:1273-1276 的 bug：routed family 短名被塞給錯的 provider。
    """

    def test_claude_returns_short_alias(self) -> None:
        """Claude 回短別名（CLI 用）。"""
        assert resolve_model_for_provider_tier("claude", 3) == "opus"
        assert resolve_model_for_provider_tier("claude", 2) == "sonnet"
        assert resolve_model_for_provider_tier("claude", 1) == "haiku"

    def test_gemini_returns_full_id(self) -> None:
        """Gemini 回完整 model id，不是短名。"""
        m3 = resolve_model_for_provider_tier("gemini", 3)
        m1 = resolve_model_for_provider_tier("gemini", 1)
        assert m3.startswith("gemini-")
        assert m1.startswith("gemini-")
        # 回傳值必須是白名單內的合法 pair
        validate_provider_model("gemini", m3)
        validate_provider_model("gemini", m1)

    def test_openai_returns_full_id(self) -> None:
        m3 = resolve_model_for_provider_tier("openai", 3)
        m2 = resolve_model_for_provider_tier("openai", 2)
        m1 = resolve_model_for_provider_tier("openai", 1)
        for m in (m3, m2, m1):
            validate_provider_model("openai", m)  # 必須合法
        assert m3 == "o3"
        assert m2 == "gpt-4o"
        assert m1 == "gpt-4o-mini"

    def test_tier_aware_cross_provider_mapping_regression(self) -> None:
        """回歸：accounts_list 有 claude+gemini+openai 三家，tier=3 時每家各自映射。

        這是 architect 抓到的 Ralph Loop bug 的核心防線：
        以前 resolve_model 回 "opus" 後直接套給 gemini account 會 raise
        IncompatibleModelError；現在每家用自己的 tier 3 model。
        """
        mixed_accounts = [("claude", "", {}, "a"), ("gemini", "", {}, "b"), ("openai", "", {}, "c")]
        tier = 3
        remapped = [
            (provider, resolve_model_for_provider_tier(provider, tier), auth, name)
            for provider, _, auth, name in mixed_accounts
        ]
        # 每個 pair 都必須通過 validate（不會有跨家錯配）
        for provider, model, _, _ in remapped:
            validate_provider_model(provider, model)
        # 明確 tier 3 對應：claude=opus, gemini=pro 家族, openai=o3
        assert remapped[0][1] == "opus"
        assert "pro" in remapped[1][1]
        assert remapped[2][1] == "o3"

    def test_unknown_tier_fallback(self) -> None:
        """未知 tier（-1/0）fallback 到 provider task 預設。"""
        r = resolve_model_for_provider_tier("openai", -1)
        # 不一定合法（預設可能為空字串），但不能崩
        assert isinstance(r, str)

    def test_unknown_provider_returns_empty(self) -> None:
        """未知 provider 不拋錯，回空字串。"""
        assert resolve_model_for_provider_tier("some-custom", 3) == ""

    def test_claude_tier_fallback_to_sonnet(self) -> None:
        """Claude 遇到 out-of-range tier (e.g. 99) 應 fallback sonnet，不爆。"""
        assert resolve_model_for_provider_tier("claude", 99) == "sonnet"
