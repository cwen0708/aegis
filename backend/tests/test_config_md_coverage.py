"""
config_md.py — chat 模式基本覆蓋測試

驗證重點：
- chat 模式基本結構 — 記憶路徑、安全區段
- user_context 帶 display_name → "當前用戶" section
- stage_name + description + instruction 全渲染（task 模式）
- 4 種 provider 回傳正確檔名和目錄
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestBuildConfigMdChatMode:
    """chat 模式 build_config_md 測試"""

    def test_build_config_md_chat_mode_basic(self):
        """chat 模式基本結構 — 含記憶路徑、安全區段"""
        fake_memory_path = "/aegis/members/xiao-yin/memory"

        with patch("app.core.member_profile.get_member_memory_dir",
                   return_value=fake_memory_path):
            from app.core.executor.config_md import build_config_md
            result = build_config_md(
                mode="chat",
                soul="你是小茵，全端工程師。",
                member_slug="xiao-yin",
            )

        # 身份
        assert "你是小茵" in result
        # 記憶路徑
        assert "# 記憶" in result
        assert fake_memory_path in result
        assert "short-term/" in result
        assert "long-term/" in result
        # 安全限制：靜態規則已移至 .claude/rules/security.md，CLAUDE.md 不再內嵌
        assert "禁止修改系統檔案" not in result

    def test_build_config_md_chat_with_user_context(self):
        """user_context 帶 display_name → 渲染「當前用戶」section"""
        fake_memory_path = "/aegis/members/xiao-yin/memory"

        user_ctx = MagicMock()
        user_ctx.display_name = "王小明"
        user_ctx.description = "資深工程師"

        with patch("app.core.member_profile.get_member_memory_dir",
                   return_value=fake_memory_path):
            from app.core.executor.config_md import build_config_md
            result = build_config_md(
                mode="chat",
                soul="你是小茵。",
                member_slug="xiao-yin",
                user_context=user_ctx,
            )

        assert "# 當前用戶" in result
        assert "王小明" in result
        assert "資深工程師" in result
        assert "根據用戶的身份和權限範圍回答" in result


class TestBuildConfigMdTaskStage:
    """task 模式 stage 欄位渲染測試"""

    def test_build_config_md_task_stage_fields(self):
        """stage_name + description + instruction 全渲染於輸出中"""
        fake_memory_path = "/aegis/members/xiao-yin/memory"

        async def _fake_retrieve(*args, **kwargs):
            return []

        with patch("app.core.member_profile.get_member_memory_dir",
                   return_value=fake_memory_path), \
             patch("app.core.executor.memory.retrieve_task_memory",
                   side_effect=_fake_retrieve):

            from app.core.executor.config_md import build_config_md
            result = build_config_md(
                mode="task",
                soul="你是小茵。",
                member_slug="xiao-yin",
                project_path="/home/user/projects/myapp",
                card_content="實作登入功能",
                stage_name="Step 1: 建立 API",
                stage_description="建立 /api/login 端點，支援 JWT。",
                stage_instruction="請先閱讀現有 auth 模組再開始實作。",
            )

        # stage 相關欄位
        assert "Step 1: 建立 API" in result
        assert "建立 /api/login 端點" in result
        assert "請先閱讀現有 auth 模組" in result
        assert "## 階段指令" in result
        # 任務內容
        assert "實作登入功能" in result
        # 記憶路徑
        assert fake_memory_path in result
        # 專案路徑
        assert "/home/user/projects/myapp" in result


class TestGetConfigFilenameAndDotDir:
    """get_config_filename / get_dot_dir 四種 provider 測試"""

    def test_get_config_filename_and_dot_dir(self):
        """4 種 provider 回傳正確檔名和目錄"""
        from app.core.executor.config_md import get_config_filename, get_dot_dir

        cases = [
            ("claude", "CLAUDE.md", ".claude"),
            ("gemini", "Gemini.md", ".gemini"),
            ("codex",  "CODEX.md",  ".codex"),
            ("ollama", "OLLAMA.md", ".ollama"),
        ]
        for provider, expected_file, expected_dir in cases:
            assert get_config_filename(provider) == expected_file, \
                f"{provider}: expected filename {expected_file}"
            assert get_dot_dir(provider) == expected_dir, \
                f"{provider}: expected dot dir {expected_dir}"

    def test_openai_provider_returns_correct_config(self):
        """openai provider 回傳 OPENAI.md 和 .openai"""
        from app.core.executor.config_md import get_config_filename, get_dot_dir

        assert get_config_filename("openai") == "OPENAI.md"
        assert get_dot_dir("openai") == ".openai"

    def test_unknown_provider_falls_back_to_claude(self):
        """未知 provider 應 fallback 至 claude 設定"""
        from app.core.executor.config_md import get_config_filename, get_dot_dir

        assert get_config_filename("unknown-provider") == "CLAUDE.md"
        assert get_dot_dir("unknown-provider") == ".claude"
