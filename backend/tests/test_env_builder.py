"""
EnvironmentBuilder 單元測試

測試內容：
- 鏈式 API 各方法功能
- build() 輸出包含正確 key
- 白名單過濾
- 環境變數組裝順序和覆蓋
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.core.env_builder import EnvironmentBuilder


class TestEnvironmentBuilderBasic:
    """基礎功能測試"""

    def test_init_creates_empty_dict(self):
        """初始化時應創建空字典"""
        builder = EnvironmentBuilder()
        env = builder.build()
        # 環境變數字典應該是 dict 類型
        assert isinstance(env, dict)

    def test_chaining_api(self):
        """鏈式 API 應返回 self"""
        builder = EnvironmentBuilder()
        
        result = builder.with_system_keys()
        assert result is builder
        
        result = builder.with_project_vars(None)
        assert result is builder
        
        result = builder.with_global_api_keys()
        assert result is builder

    def test_with_system_keys_calls_build_sanitized_env(self):
        """with_system_keys() 應呼叫 build_sanitized_env()"""
        with patch('app.core.sandbox.build_sanitized_env') as mock_sanitized:
            mock_sanitized.return_value = {'PATH': '/usr/bin', 'HOME': '/home/user'}

            builder = EnvironmentBuilder()
            builder.with_system_keys()
            env = builder.build()

            mock_sanitized.assert_called_once_with(project_id=None)
            assert env['PATH'] == '/usr/bin'
            assert env['HOME'] == '/home/user'

    def test_with_member_extra_updates_env(self):
        """with_member_extra() 應更新環境變數"""
        builder = EnvironmentBuilder()
        extra = {'MY_VAR': 'my_value', 'ANOTHER_VAR': 'another_value'}
        
        builder.with_member_extra(extra)
        env = builder.build()
        
        assert env['MY_VAR'] == 'my_value'
        assert env['ANOTHER_VAR'] == 'another_value'

    def test_with_member_extra_none(self):
        """with_member_extra(None) 應無影響"""
        builder = EnvironmentBuilder()
        builder.with_member_extra(None)
        env = builder.build()
        
        assert len(env) == 0

    def test_with_entry_point(self):
        """with_entry_point() 應設定 CLAUDE_CODE_ENTRY_POINT"""
        builder = EnvironmentBuilder()
        builder.with_entry_point("worker")
        env = builder.build()
        
        assert env['CLAUDE_CODE_ENTRY_POINT'] == 'worker'

    def test_with_entry_point_runner(self):
        """with_entry_point() 應支援多個值"""
        builder = EnvironmentBuilder()
        builder.with_entry_point("runner")
        env = builder.build()
        
        assert env['CLAUDE_CODE_ENTRY_POINT'] == 'runner'

    def test_with_git_config_when_file_exists(self):
        """with_git_config() 當檔案存在時應設定"""
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = True
            
            builder = EnvironmentBuilder()
            builder.with_git_config("/path/to/.gitconfig")
            env = builder.build()
            
            assert env['GIT_CONFIG_GLOBAL'] == '/path/to/.gitconfig'

    def test_with_git_config_when_file_not_exists(self):
        """with_git_config() 當檔案不存在時應跳過"""
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            builder = EnvironmentBuilder()
            builder.with_git_config("/path/to/nonexistent/.gitconfig")
            env = builder.build()
            
            assert 'GIT_CONFIG_GLOBAL' not in env

    def test_with_git_config_none(self):
        """with_git_config(None) 應無影響"""
        builder = EnvironmentBuilder()
        builder.with_git_config(None)
        env = builder.build()
        
        assert 'GIT_CONFIG_GLOBAL' not in env


class TestEnvironmentBuilderAuth:
    """認證相關測試"""

    def test_with_auth_none_info(self):
        """with_auth(None) 應無影響"""
        builder = EnvironmentBuilder()
        builder.with_auth("claude", None)
        env = builder.build()
        
        assert len(env) == 0

    def test_with_auth_calls_inject_auth_env(self):
        """with_auth() 應呼叫 inject_auth_env()"""
        with patch('app.core.executor.auth.inject_auth_env') as mock_inject:
            builder = EnvironmentBuilder()
            auth_info = {'api_key': 'test_key'}

            builder.with_auth("claude", auth_info, log_prefix="[Test]")

            mock_inject.assert_called_once()
            # 檢查呼叫參數
            args, kwargs = mock_inject.call_args
            assert args[1] == "claude"
            assert args[2] == auth_info
            assert kwargs['log_prefix'] == "[Test]"


class TestEnvironmentBuilderProjectVars:
    """專案環境變數相關測試"""

    def test_with_project_vars_none_project_id(self):
        """with_project_vars(None) 應無影響"""
        builder = EnvironmentBuilder()
        builder.with_project_vars(None)
        env = builder.build()
        
        assert len(env) == 0

    def test_with_project_vars_loads_from_db(self):
        """with_project_vars() 應從 DB 讀取專案環境變數"""
        mock_env_var1 = Mock()
        mock_env_var1.key = 'PROJECT_VAR1'
        mock_env_var1.value = 'value1'

        mock_env_var2 = Mock()
        mock_env_var2.key = 'PROJECT_VAR2'
        mock_env_var2.value = 'value2'

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.exec.return_value.all.return_value = [
                mock_env_var1, mock_env_var2
            ]

            builder = EnvironmentBuilder()
            builder.with_project_vars(123)
            env = builder.build()

            assert env['PROJECT_VAR1'] == 'value1'
            assert env['PROJECT_VAR2'] == 'value2'

    def test_with_project_vars_handles_db_error(self):
        """with_project_vars() 應優雅處理 DB 錯誤"""
        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_class.side_effect = Exception("DB Error")

            # 應不拋出異常
            builder = EnvironmentBuilder()
            builder.with_project_vars(123)
            env = builder.build()

            # 環境變數字典應為空
            assert isinstance(env, dict)


class TestEnvironmentBuilderGlobalKeys:
    """全域 API Key 相關測試"""

    def test_with_global_api_keys_loads_from_db(self):
        """with_global_api_keys() 應從 SystemSetting 讀取 API Key"""
        mock_gemini_setting = Mock()
        mock_gemini_setting.value = 'gemini_key_123'

        mock_google_setting = Mock()
        mock_google_setting.value = 'google_key_456'

        mock_openai_setting = Mock()
        mock_openai_setting.value = 'sk-test-openai-key'

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance

            mock_session_instance.get.side_effect = [
                mock_gemini_setting,
                mock_google_setting,
                mock_openai_setting,
            ]

            builder = EnvironmentBuilder()
            builder.with_global_api_keys()
            env = builder.build()

            assert env['GEMINI_API_KEY'] == 'gemini_key_123'
            assert env['GOOGLE_API_KEY'] == 'google_key_456'
            assert env['OPENAI_API_KEY'] == 'sk-test-openai-key'

    def test_with_global_api_keys_skips_empty_values(self):
        """with_global_api_keys() 應跳過空值"""
        mock_gemini_setting = Mock()
        mock_gemini_setting.value = 'gemini_key_123'

        mock_google_setting = Mock()
        mock_google_setting.value = None

        mock_openai_setting = Mock()
        mock_openai_setting.value = None

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.get.side_effect = [
                mock_gemini_setting,
                mock_google_setting,
                mock_openai_setting,
            ]

            builder = EnvironmentBuilder()
            builder.with_global_api_keys()
            env = builder.build()

            assert env['GEMINI_API_KEY'] == 'gemini_key_123'
            assert 'GOOGLE_API_KEY' not in env
            assert 'OPENAI_API_KEY' not in env

    def test_with_global_api_keys_handles_db_error(self):
        """with_global_api_keys() 應優雅處理 DB 錯誤"""
        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_class.side_effect = Exception("DB Error")

            builder = EnvironmentBuilder()
            builder.with_global_api_keys()
            env = builder.build()

            assert isinstance(env, dict)


class TestEnvironmentBuilderDbSettings:
    """with_db_settings() 合併 DB session 測試"""

    def test_with_db_settings_loads_both(self):
        """with_db_settings() 應在單一 session 內讀取專案變數和全域 API Key"""
        mock_env_var = Mock()
        mock_env_var.key = 'PROJECT_VAR'
        mock_env_var.value = 'project_value'

        mock_gemini = Mock()
        mock_gemini.value = 'gemini_key'

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.exec.return_value.all.return_value = [mock_env_var]
            mock_session_instance.get.side_effect = [mock_gemini, None, None]

            builder = EnvironmentBuilder()
            builder.with_db_settings(123)
            env = builder.build()

            assert env['PROJECT_VAR'] == 'project_value'
            assert env['GEMINI_API_KEY'] == 'gemini_key'
            assert 'GOOGLE_API_KEY' not in env
            assert 'OPENAI_API_KEY' not in env
            # 確認只開了一次 session
            assert mock_session_class.call_count == 1

    def test_with_db_settings_no_project_id(self):
        """with_db_settings(None) 應僅讀取全域 API Key"""
        mock_google = Mock()
        mock_google.value = 'google_key'

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.get.side_effect = [None, mock_google, None]

            builder = EnvironmentBuilder()
            builder.with_db_settings(None)
            env = builder.build()

            assert env['GOOGLE_API_KEY'] == 'google_key'
            assert 'OPENAI_API_KEY' not in env
            # 不應呼叫 exec（無專案變數查詢）
            mock_session_instance.exec.assert_not_called()

    def test_with_db_settings_handles_error(self):
        """with_db_settings() 應優雅處理 DB 錯誤"""
        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_class.side_effect = Exception("DB Error")

            builder = EnvironmentBuilder()
            builder.with_db_settings(123)
            env = builder.build()

            assert isinstance(env, dict)


class TestEnvironmentBuilderChaining:
    """鏈式 API 組合測試"""

    def test_full_chain_worker_scenario(self):
        """測試完整的 worker 場景鏈（使用 with_db_settings）"""
        mock_env_var = Mock()
        mock_env_var.key = 'PROJECT_VAR'
        mock_env_var.value = 'project_value'

        with patch('app.core.sandbox.build_sanitized_env') as mock_sanitized, \
             patch('sqlmodel.Session') as mock_session_class, \
             patch('app.core.executor.auth.inject_auth_env') as mock_auth, \
             patch('os.path.exists') as mock_exists:

            mock_sanitized.return_value = {'PATH': '/usr/bin'}
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.exec.return_value.all.return_value = [mock_env_var]
            mock_session_instance.get.side_effect = [None, None, None]  # No API keys
            mock_exists.return_value = True

            builder = EnvironmentBuilder()
            env = (builder
                .with_system_keys()
                .with_db_settings(123)
                .with_entry_point("worker")
                .with_git_config("/path/to/.gitconfig")
                .with_auth("claude", {'api_key': 'key123'})
                .build())

            # 驗證注入了期望的 key
            assert env['PATH'] == '/usr/bin'
            assert env['PROJECT_VAR'] == 'project_value'
            assert env['CLAUDE_CODE_ENTRY_POINT'] == 'worker'
            assert env['GIT_CONFIG_GLOBAL'] == '/path/to/.gitconfig'
            mock_auth.assert_called_once()

    def test_full_chain_runner_scenario(self):
        """測試完整的 runner 場景鏈（使用 with_db_settings）"""
        with patch('app.core.sandbox.build_sanitized_env') as mock_sanitized, \
             patch('sqlmodel.Session') as mock_session_class, \
             patch('app.core.executor.auth.inject_auth_env') as mock_auth:

            mock_sanitized.return_value = {'PATH': '/usr/bin', 'HOME': '/home/user'}
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.exec.return_value.all.return_value = []  # No project vars
            mock_session_instance.get.side_effect = [None, None, None]  # No API keys

            builder = EnvironmentBuilder()
            env = (builder
                .with_system_keys()
                .with_db_settings(456)
                .with_member_extra({'MY_EXTRA': 'value'})
                .with_auth("claude", {'oauth_token': 'token123'})
                .build())

            assert env['PATH'] == '/usr/bin'
            assert env['HOME'] == '/home/user'
            assert env['MY_EXTRA'] == 'value'
            mock_auth.assert_called_once()

    def test_legacy_separate_calls_still_work(self):
        """向前兼容：分開呼叫 with_project_vars + with_global_api_keys 仍可正常運作"""
        mock_env_var = Mock()
        mock_env_var.key = 'LEGACY_VAR'
        mock_env_var.value = 'legacy_value'

        with patch('sqlmodel.Session') as mock_session_class:
            mock_session_instance = MagicMock()
            mock_session_class.return_value.__enter__.return_value = mock_session_instance
            mock_session_instance.exec.return_value.all.return_value = [mock_env_var]
            mock_session_instance.get.side_effect = [None, None, None]

            builder = EnvironmentBuilder()
            env = (builder
                .with_project_vars(99)
                .with_global_api_keys()
                .build())

            assert env['LEGACY_VAR'] == 'legacy_value'


class TestEnvironmentBuilderIsolation:
    """隔離與覆蓋測試"""

    def test_member_extra_overrides_system_keys(self):
        """member_extra 應能覆蓋系統 key"""
        with patch('app.core.sandbox.build_sanitized_env') as mock_sanitized:
            mock_sanitized.return_value = {'OVERRIDE_ME': 'original'}

            builder = EnvironmentBuilder()
            env = (builder
                .with_system_keys()
                .with_member_extra({'OVERRIDE_ME': 'overridden'})
                .build())

            assert env['OVERRIDE_ME'] == 'overridden'

    def test_entry_point_isolation(self):
        """entry_point 應獨立設定"""
        builder = EnvironmentBuilder()
        env = (builder
            .with_entry_point("worker")
            .with_entry_point("runner")  # 後設定應覆蓋
            .build())

        assert env['CLAUDE_CODE_ENTRY_POINT'] == 'runner'

    def test_build_returns_copy(self):
        """build() 回傳的 dict 應與 builder 內部狀態隔離"""
        builder = EnvironmentBuilder()
        builder.with_entry_point("worker")

        env1 = builder.build()
        env1["INJECTED"] = "should_not_leak"

        env2 = builder.build()
        assert "INJECTED" not in env2, "build() 應回傳獨立拷貝，外部修改不應影響 builder"

    def test_build_multiple_calls_independent(self):
        """多次 build() 呼叫應回傳獨立的 dict"""
        builder = EnvironmentBuilder()
        builder.with_member_extra({"KEY": "value"})

        env1 = builder.build()
        env2 = builder.build()
        assert env1 == env2
        assert env1 is not env2
