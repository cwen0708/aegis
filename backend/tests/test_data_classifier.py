"""資料安全分類規則引擎 — 單元測試"""
import pytest
from app.core.data_classifier import (
    SecurityLevel,
    classify,
    scan,
    sanitize,
    restore,
)


class TestClassify:
    """classify() 分類測試。"""

    def test_classify_s3_openai_key(self):
        """含 OpenAI API key 的文字應被分類為 S3。"""
        text = "my key is sk-abc123def456ghi789jkl012mno"
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_anthropic_key(self):
        """含 Anthropic API key 的文字應被分類為 S3。"""
        text = "export ANTHROPIC_API_KEY=sk-ant-abcdef1234567890abcdef"
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_github_token(self):
        """含 GitHub token 的文字應被分類為 S3。"""
        text = "token: ghp_ABCDEFghijklmnopqrstuvwx"
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_jwt(self):
        """含 JWT token 的文字應被分類為 S3。"""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        assert classify(f"Bearer {jwt}") == SecurityLevel.S3

    def test_classify_s3_password(self):
        """含密碼賦值的文字應被分類為 S3。"""
        text = 'password="MyS3cretP@ss!"'
        assert classify(text) == SecurityLevel.S3

    def test_classify_s2_email(self):
        """含 email 的文字應被分類為 S2。"""
        text = "請聯繫 user@example.com 取得詳細資訊"
        assert classify(text) == SecurityLevel.S2

    def test_classify_s2_phone(self):
        """含台灣手機號碼的文字應被分類為 S2。"""
        text = "聯絡電話：0912-345-678"
        assert classify(text) == SecurityLevel.S2

    def test_classify_s2_tw_id(self):
        """含台灣身分證字號的文字應被分類為 S2。"""
        text = "身分證字號 A123456789"
        assert classify(text) == SecurityLevel.S2

    def test_classify_s2_credit_card(self):
        """含信用卡號的文字應被分類為 S2。"""
        text = "卡號：4111 1111 1111 1111"
        assert classify(text) == SecurityLevel.S2

    def test_classify_s1_normal(self):
        """一般文字應被分類為 S1。"""
        text = "今天天氣真好，我們來開個會討論一下專案進度吧！"
        assert classify(text) == SecurityLevel.S1

    def test_classify_s1_empty(self):
        """空字串應被分類為 S1。"""
        assert classify("") == SecurityLevel.S1


class TestScan:
    """scan() 掃描測試。"""

    def test_scan_returns_matches(self):
        """掃描應回傳正確的命中結果。"""
        text = "email: test@example.com"
        matches = scan(text)
        assert len(matches) >= 1
        assert matches[0].pattern_name == "email"
        assert matches[0].level == SecurityLevel.S2

    def test_scan_no_match(self):
        """無敏感資料的文字掃描應回傳空列表。"""
        assert scan("hello world") == []

    def test_scan_multiple_patterns(self):
        """同時含 S2 和 S3 的文字應回傳多個命中。"""
        text = "key=sk-abc123def456ghi789jkl012mno email=admin@test.com"
        matches = scan(text)
        levels = {m.level for m in matches}
        assert SecurityLevel.S3 in levels
        assert SecurityLevel.S2 in levels


class TestMultiplePatterns:
    """多重規則交互測試。"""

    def test_mixed_s2_s3_returns_s3(self):
        """同時含 S2 和 S3 的文字，classify 應回傳 S3。"""
        text = "user@example.com sk-ant-abcdef1234567890abcdef"
        assert classify(text) == SecurityLevel.S3


class TestSanitizeRestore:
    """sanitize() / restore() 遮蔽與還原測試。"""

    def test_sanitize_restore_roundtrip(self):
        """遮蔽後還原應等於原始文字。"""
        original = "請聯繫 admin@corp.com 或撥打 0912-345-678"
        redacted, mapping = sanitize(original)
        assert "admin@corp.com" not in redacted
        assert "0912-345-678" not in redacted
        restored = restore(redacted, mapping)
        assert restored == original

    def test_sanitize_s3_roundtrip(self):
        """S3 等級的資料遮蔽後還原應等於原始文字。"""
        original = "export KEY=sk-ant-abcdef1234567890abcdef"
        redacted, mapping = sanitize(original)
        assert "sk-ant-" not in redacted
        restored = restore(redacted, mapping)
        assert restored == original

    def test_sanitize_no_sensitive(self):
        """無敏感資料時 sanitize 應回傳原文與空 mapping。"""
        text = "這是一段普通文字"
        redacted, mapping = sanitize(text)
        assert redacted == text
        assert mapping == {}


class TestNoFalsePositive:
    """誤判防護測試。"""

    def test_normal_code_no_false_positive(self):
        """一般程式碼片段不應觸發誤判。"""
        code_snippets = [
            "def calculate(x, y): return x + y",
            "for i in range(100): print(i)",
            "import os; path = os.path.join('a', 'b')",
            "result = {'status': 'ok', 'count': 42}",
            "SELECT id, name FROM users WHERE active = 1",
        ]
        for snippet in code_snippets:
            assert classify(snippet) == SecurityLevel.S1, f"誤判: {snippet}"

    def test_short_sk_prefix_no_match(self):
        """短的 sk- 前綴不應誤判為 API key。"""
        # sk- 後面不夠長，不該命中
        assert classify("variable sk-short") == SecurityLevel.S1

    def test_url_with_numbers_no_credit_card(self):
        """URL 中的長數字不應被誤判為信用卡號。"""
        text = "https://example.com/page/12345"
        assert classify(text) == SecurityLevel.S1
