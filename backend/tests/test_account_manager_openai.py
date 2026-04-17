"""
account_manager — OpenAI 健康檢查分支測試

驗證 select_best_account() 對 OpenAI provider 的行為：
- API Key 存在且 sk- 開頭 → 回傳帳號
- API Key 不存在或格式不對 → 跳過
"""
import pytest
from unittest.mock import Mock, MagicMock, patch


def _make_binding_and_account(provider="openai", is_healthy=True):
    """建立 mock binding + account"""
    account = Mock()
    account.id = 1
    account.provider = provider
    account.is_healthy = is_healthy
    account.name = "test-openai"
    account.credential_file = "test.json"

    binding = Mock()
    binding.account_id = account.id
    binding.priority = 1
    binding.model = "gpt-4o"

    return binding, account


class TestSelectBestAccountOpenAI:
    """OpenAI 分支健康檢查測試"""

    def test_openai_valid_key_returns_account(self):
        """有效 sk- 開頭的 API Key 應回傳帳號"""
        binding, account = _make_binding_and_account()

        with patch("sqlmodel.Session") as mock_session_class, \
             patch("app.core.env_builder.EnvironmentBuilder") as mock_builder_class, \
             patch("app.core.account_manager.activate_account") as mock_activate:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session
            mock_session.exec.return_value.all.return_value = [binding]
            mock_session.get.return_value = account

            # Mock EnvironmentBuilder chain
            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.with_db_settings.return_value = mock_builder
            mock_builder.build.return_value = {"OPENAI_API_KEY": "sk-proj-abc123"}

            from app.core.account_manager import select_best_account
            result = select_best_account(mock_session, member_id=1)

            assert result is account
            mock_activate.assert_called_once_with(account)

    def test_openai_missing_key_skips(self):
        """缺少 API Key 時應跳過 OpenAI 帳號"""
        binding, account = _make_binding_and_account()

        with patch("sqlmodel.Session") as mock_session_class, \
             patch("app.core.env_builder.EnvironmentBuilder") as mock_builder_class:
            mock_session = MagicMock()
            mock_session.exec.return_value.all.return_value = [binding]
            mock_session.get.return_value = account

            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.with_db_settings.return_value = mock_builder
            mock_builder.build.return_value = {}  # No key

            from app.core.account_manager import select_best_account
            result = select_best_account(mock_session, member_id=1)

            assert result is None

    def test_openai_invalid_key_format_skips(self):
        """API Key 格式不正確（非 sk- 開頭）應跳過"""
        binding, account = _make_binding_and_account()

        with patch("sqlmodel.Session") as mock_session_class, \
             patch("app.core.env_builder.EnvironmentBuilder") as mock_builder_class:
            mock_session = MagicMock()
            mock_session.exec.return_value.all.return_value = [binding]
            mock_session.get.return_value = account

            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.with_db_settings.return_value = mock_builder
            mock_builder.build.return_value = {"OPENAI_API_KEY": "invalid-key-no-prefix"}

            from app.core.account_manager import select_best_account
            result = select_best_account(mock_session, member_id=1)

            assert result is None

    def test_openai_unhealthy_account_skips(self):
        """is_healthy=False 的帳號應被跳過"""
        binding, account = _make_binding_and_account(is_healthy=False)

        with patch("sqlmodel.Session") as mock_session_class, \
             patch("app.core.env_builder.EnvironmentBuilder") as mock_builder_class:
            mock_session = MagicMock()
            mock_session.exec.return_value.all.return_value = [binding]
            mock_session.get.return_value = account

            from app.core.account_manager import select_best_account
            result = select_best_account(mock_session, member_id=1)

            assert result is None
            # EnvironmentBuilder should not be called for unhealthy accounts
            mock_builder_class.assert_not_called()
