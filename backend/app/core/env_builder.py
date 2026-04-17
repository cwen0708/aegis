"""
EnvironmentBuilder — 鏈式 API 統一環境變數組裝邏輯

支援以下模式：
- .with_system_keys() → 呼叫 build_sanitized_env() 的白名單邏輯
- .with_db_settings(project_id) → 單一 session 讀取專案變數 + 全域 API key
- .with_project_vars(project_id) → 注入專案環境變數（向前兼容）
- .with_global_api_keys() → 注入全域 API key（向前兼容）
- .with_member_extra(extra_env) → 注入 MCP 額外環境變數（AD creds 等）
- .with_auth(provider, auth_info) → 呼叫 inject_auth_env
- .with_entry_point(name) → 設定 CLAUDE_CODE_ENTRY_POINT
- .with_git_config(path) → 設定 GIT_CONFIG_GLOBAL
- .build() → Dict[str, str]

使用範例：
    env = (EnvironmentBuilder()
        .with_system_keys()
        .with_db_settings(project_id)
        .with_member_extra(extra_env)
        .with_auth(provider_name, auth_info)
        .build())
"""
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# SystemSetting key → 環境變數 key 的對應
_GLOBAL_KEY_MAPPING: tuple[tuple[str, str], ...] = (
    ("gemini_api_key", "GEMINI_API_KEY"),
    ("google_api_key", "GOOGLE_API_KEY"),
    ("openai_api_key", "OPENAI_API_KEY"),
)


class EnvironmentBuilder:
    """環境變數鏈式建造者"""

    def __init__(self):
        self._env: Dict[str, str] = {}

    def with_system_keys(self) -> "EnvironmentBuilder":
        """添加系統白名單環境變數（呼叫 sandbox.build_sanitized_env()）"""
        from app.core.sandbox import build_sanitized_env

        # 用 build_sanitized_env(project_id=None) 獲取白名單環境變數
        # 不需要注入 project vars，這部分由 with_project_vars() 負責
        sanitized = build_sanitized_env(project_id=None)
        self._env.update(sanitized)
        return self

    def with_db_settings(self, project_id: Optional[int]) -> "EnvironmentBuilder":
        """單一 DB session 內讀取專案環境變數 + 全域 API Key"""
        try:
            from sqlmodel import Session, select
            from app.database import engine
            from app.models.core import ProjectEnvVar, SystemSetting

            with Session(engine) as session:
                # 專案環境變數
                if project_id:
                    env_vars = session.exec(
                        select(ProjectEnvVar).where(ProjectEnvVar.project_id == project_id)
                    ).all()
                    for v in env_vars:
                        self._env[v.key] = v.value

                # 全域 API Key
                for setting_key, env_key in _GLOBAL_KEY_MAPPING:
                    setting = session.get(SystemSetting, setting_key)
                    if setting and setting.value:
                        self._env[env_key] = setting.value
        except Exception as e:
            logger.warning(f"[EnvironmentBuilder] Failed to load DB settings: {e}")

        return self

    def with_project_vars(self, project_id: Optional[int]) -> "EnvironmentBuilder":
        """注入專案環境變數（向前兼容，建議改用 with_db_settings）"""
        if not project_id:
            return self

        try:
            from sqlmodel import Session, select
            from app.database import engine
            from app.models.core import ProjectEnvVar

            with Session(engine) as session:
                env_vars = session.exec(
                    select(ProjectEnvVar).where(ProjectEnvVar.project_id == project_id)
                ).all()
                for v in env_vars:
                    self._env[v.key] = v.value
        except Exception as e:
            logger.warning(f"[EnvironmentBuilder] Failed to load project env vars: {e}")

        return self

    def with_global_api_keys(self) -> "EnvironmentBuilder":
        """注入全域 API Key（向前兼容，獨立 DB session）"""
        try:
            from sqlmodel import Session
            from app.database import engine
            from app.models.core import SystemSetting

            with Session(engine) as session:
                for setting_key, env_key in _GLOBAL_KEY_MAPPING:
                    setting = session.get(SystemSetting, setting_key)
                    if setting and setting.value:
                        self._env[env_key] = setting.value
        except Exception as e:
            logger.warning(f"[EnvironmentBuilder] Failed to load SystemSetting keys: {e}")

        return self

    def with_member_extra(self, extra_env: Optional[Dict[str, str]]) -> "EnvironmentBuilder":
        """注入 MCP 額外環境變數（AD creds 等）"""
        if extra_env:
            self._env.update(extra_env)
        return self

    def with_auth(
        self,
        provider: str,
        auth_info: Optional[Dict[str, str]],
        *,
        log_prefix: str = "",
    ) -> "EnvironmentBuilder":
        """注入認證信息（呼叫 inject_auth_env）"""
        if not auth_info:
            return self

        from app.core.executor.auth import inject_auth_env

        inject_auth_env(self._env, provider, auth_info, log_prefix=log_prefix)
        return self

    def with_entry_point(self, name: str) -> "EnvironmentBuilder":
        """設定 CLAUDE_CODE_ENTRY_POINT"""
        self._env["CLAUDE_CODE_ENTRY_POINT"] = name
        return self

    def with_git_config(self, path: Optional[str]) -> "EnvironmentBuilder":
        """設定 GIT_CONFIG_GLOBAL"""
        if path and os.path.exists(path):
            self._env["GIT_CONFIG_GLOBAL"] = path
        return self

    def build(self) -> Dict[str, str]:
        """返回最終環境變數字典（防禦性拷貝，避免外部修改影響 builder 內部狀態）"""
        return dict(self._env)
