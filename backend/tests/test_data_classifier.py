"""資料安全分類規則引擎 — 單元測試"""
import os
import pytest
from app.core.data_classifier import (
    SecurityLevel,
    classify,
    scan,
    sanitize,
    restore,
    guard_for_ai,
    SecurityBlock,
    _load_project_patterns,
    get_all_patterns,
    _ALL_PATTERNS,
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

    def test_classify_s3_db_connection_string(self):
        """含資料庫連線字串（含密碼）應被分類為 S3。"""
        text = "DATABASE_URL=postgresql://admin:s3cretPass@db.example.com:5432/mydb"
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_pem_private_key(self):
        """含 PEM 私鑰 header 應被分類為 S3。"""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_gcp_api_key(self):
        """含 Google Cloud API key 應被分類為 S3。"""
        text = "GOOGLE_API_KEY=AIzaSyA1234567890abcdefghijklmnopqrstuvw"
        assert classify(text) == SecurityLevel.S3

    def test_classify_s3_slack_token(self):
        """含 Slack API token 應被分類為 S3。"""
        text = "SLACK_TOKEN=xoxb-1234567890-abcdefghij"
        assert classify(text) == SecurityLevel.S3


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

    def test_no_false_positive_normal_url(self):
        """普通 URL（含 https、http）不應被誤判為敏感資料。"""
        urls = [
            "https://example.com/api/v1/users",
            "http://localhost:8080/health",
            "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js",
            "http://192.168.1.1:3000/dashboard",
        ]
        for url in urls:
            assert classify(url) == SecurityLevel.S1, f"誤判: {url}"


class TestGuardForAi:
    """guard_for_ai() 安全閘門測試。"""

    def test_guard_s1_passthrough(self):
        """S1 普通文字應原文放行。"""
        text = "今天天氣真好，我們來討論一下專案進度"
        result_text, mapping = guard_for_ai(text)
        assert result_text == text
        assert mapping == {}

    def test_guard_s2_sanitized(self):
        """S2 含 email 的文字應被去敏化。"""
        text = "請聯繫 admin@corp.com 取得詳細資訊"
        result_text, mapping = guard_for_ai(text)
        assert "admin@corp.com" not in result_text
        assert len(mapping) > 0

    def test_guard_s3_blocked(self):
        """S3 含 API key 的文字應拋出 SecurityBlock。"""
        text = "my key is sk-abc123def456ghi789jkl012mno"
        with pytest.raises(SecurityBlock, match="S3 data detected"):
            guard_for_ai(text)

    def test_guard_integration_with_harden(self):
        """guard_for_ai + harden_prompt 協作正確：先 harden 再 guard。"""
        from app.core.prompt_hardening import harden_prompt
        prompt = "請幫我查看 user@example.com 的帳號狀態"
        hardened = harden_prompt(prompt, "/tmp/test")
        result_text, mapping = guard_for_ai(hardened)
        assert "user@example.com" not in result_text
        assert len(mapping) > 0

    def test_guard_with_project_path_custom_s3(self, tmp_path):
        """guard_for_ai 搭配自訂 S3 規則應阻擋。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: internal_token\n"
            '    regex: "INTERNAL-[A-Z0-9]{16}"\n'
            "    level: S3\n"
        )
        text = "token is INTERNAL-ABCDEF1234567890"
        with pytest.raises(SecurityBlock, match="S3 data detected"):
            guard_for_ai(text, str(tmp_path))

    def test_guard_with_project_path_custom_s2(self, tmp_path):
        """guard_for_ai 搭配自訂 S2 規則應去敏化。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: employee_id\n"
            '    regex: "EMP-\\\\d{6}"\n'
            "    level: S2\n"
        )
        text = "員工編號 EMP-123456 的資料"
        result_text, mapping = guard_for_ai(text, str(tmp_path))
        assert "EMP-123456" not in result_text
        assert len(mapping) > 0


class TestLoadProjectPatterns:
    """_load_project_patterns() 自訂規則載入測試。"""

    def test_load_valid_yaml(self, tmp_path):
        """正確的 YAML 應回傳規則列表。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: custom_key\n"
            '    regex: "CUSTOM-[A-Z]{10}"\n'
            "    level: S3\n"
            "  - name: order_id\n"
            '    regex: "ORD-\\\\d{8}"\n'
            "    level: S2\n"
        )
        patterns = _load_project_patterns(str(tmp_path))
        assert len(patterns) == 2
        assert patterns[0][0] == "custom_key"
        assert patterns[0][2] == SecurityLevel.S3
        assert patterns[1][0] == "order_id"
        assert patterns[1][2] == SecurityLevel.S2

    def test_load_missing_file(self, tmp_path):
        """設定檔不存在應回傳空列表。"""
        patterns = _load_project_patterns(str(tmp_path))
        assert patterns == []

    def test_load_invalid_yaml(self, tmp_path):
        """無效 YAML 應回傳空列表。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(":::invalid yaml:::")
        patterns = _load_project_patterns(str(tmp_path))
        assert patterns == []

    def test_load_invalid_regex(self, tmp_path):
        """包含無效 regex 的規則應被跳過。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: bad_regex\n"
            '    regex: "[invalid(("\n'
            "    level: S3\n"
            "  - name: good_one\n"
            '    regex: "GOOD-[A-Z]{5}"\n'
            "    level: S2\n"
        )
        patterns = _load_project_patterns(str(tmp_path))
        assert len(patterns) == 1
        assert patterns[0][0] == "good_one"

    def test_load_missing_fields(self, tmp_path):
        """缺少必要欄位的規則應被跳過。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: no_regex\n"
            "    level: S3\n"
            "  - regex: 'no_name'\n"
            "    level: S2\n"
            "  - name: no_level\n"
            '    regex: "NOLEVEL-\\\\d+"\n'
        )
        patterns = _load_project_patterns(str(tmp_path))
        assert patterns == []

    def test_load_invalid_level(self, tmp_path):
        """level 不是 S2/S3 的規則應被跳過。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: s1_attempt\n"
            '    regex: "S1DATA-\\\\d+"\n'
            "    level: S1\n"
        )
        patterns = _load_project_patterns(str(tmp_path))
        assert patterns == []


class TestGetAllPatterns:
    """get_all_patterns() 合併測試。"""

    def test_no_project_path(self):
        """不傳 project_path 應回傳內建規則。"""
        result = get_all_patterns()
        assert result is _ALL_PATTERNS

    def test_no_config_file(self, tmp_path):
        """project_path 沒有設定檔應回傳內建規則。"""
        result = get_all_patterns(str(tmp_path))
        assert result is _ALL_PATTERNS

    def test_merge_custom_patterns(self, tmp_path):
        """有設定檔時應合併內建 + 自訂規則。"""
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "desensitize.yaml").write_text(
            "patterns:\n"
            "  - name: my_rule\n"
            '    regex: "MYRULE-\\\\d+"\n'
            "    level: S2\n"
        )
        result = get_all_patterns(str(tmp_path))
        assert len(result) == len(_ALL_PATTERNS) + 1
        names = [r[0] for r in result]
        assert "my_rule" in names
