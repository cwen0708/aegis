"""
成本計算模塊測試
"""
import pytest
from app.core.cost_calculator import calculate_cost, extract_model_family


class TestCostCalculator:
    """測試成本計算邏輯"""

    def test_extract_model_family(self):
        """測試 model 家族名稱提取"""
        assert extract_model_family("claude-opus-4-6") == "opus"
        assert extract_model_family("claude-sonnet-4-6") == "sonnet"
        assert extract_model_family("claude-haiku-4-5") == "haiku"
        assert extract_model_family("gemini-2.0-flash") == "gemini"
        assert extract_model_family("") == "haiku"

    def test_calculate_cost_haiku(self):
        """測試 Haiku 成本計算"""
        # Haiku: $0.80 input / $4.00 output per 1M tokens
        cost = calculate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
        expected = 0.80 + 4.00
        assert abs(cost - expected) < 0.01

    def test_calculate_cost_sonnet(self):
        """測試 Sonnet 成本計算"""
        # Sonnet: $3.00 input / $15.00 output per 1M tokens
        cost = calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        expected = 3.00 + 15.00
        assert abs(cost - expected) < 0.01

    def test_calculate_cost_opus(self):
        """測試 Opus 成本計算"""
        # Opus: $15.00 input / $75.00 output per 1M tokens
        cost = calculate_cost("claude-opus-4-6", 1_000_000, 1_000_000)
        expected = 15.00 + 75.00
        assert abs(cost - expected) < 0.01

    def test_calculate_cost_zero(self):
        """測試零 token 成本"""
        cost = calculate_cost("claude-haiku-4-5", 0, 0)
        assert cost == 0.0

    def test_calculate_cost_invalid_model(self):
        """測試未知 model 的成本計算（應該 fallback 到 Haiku）"""
        cost = calculate_cost("unknown-model", 1_000_000, 1_000_000)
        expected = 0.80 + 4.00  # Haiku 預設
        assert abs(cost - expected) < 0.01

    def test_calculate_cost_partial_tokens(self):
        """測試部分 token 的成本計算"""
        # 500k input + 100k output，使用 Haiku 定價
        cost = calculate_cost("claude-haiku-4-5", 500_000, 100_000)
        expected = (500_000 / 1_000_000) * 0.80 + (100_000 / 1_000_000) * 4.00
        assert abs(cost - expected) < 0.0001

    def test_calculate_cost_negative_tokens(self):
        """測試負數 token（應該返回 0）"""
        cost = calculate_cost("claude-haiku-4-5", -1000, 500)
        assert cost == 0.0

    def test_calculate_cost_none_model(self):
        """測試 None model（應該 fallback 到 Haiku）"""
        cost = calculate_cost(None, 1_000_000, 1_000_000)
        expected = 0.80 + 4.00
        assert abs(cost - expected) < 0.01
