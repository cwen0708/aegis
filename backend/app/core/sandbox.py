"""
Sandbox utilities — environment sanitisation and process isolation for AI tasks.

Key design:
- Whitelist-only environment variables (no secrets leak)
- Per-project env var injection from DB
- Linux user isolation via setuid (optional)
- Process group isolation via start_new_session / CREATE_NEW_PROCESS_GROUP
"""
import os
import platform
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 白名單：只有這些環境變數會傳給 AI subprocess ──
ALLOWED_ENV_KEYS = {
    # 系統必要
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL",
    "TMPDIR", "TMP", "TEMP",
    # Windows 必要
    "SystemRoot", "SYSTEMROOT", "COMSPEC", "PATHEXT",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "ProgramFiles", "ProgramFiles(x86)", "CommonProgramFiles",
    "HOMEDRIVE", "HOMEPATH",
    # Git
    "GIT_CONFIG_GLOBAL", "GIT_EXEC_PATH",
    # Node / npm / pnpm
    "NODE_PATH", "NVM_DIR",
    # AI CLI 認證（這些由 Account 系統管理，但部分環境仍需透過環境變數傳遞）
    "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
    # XDG（Linux CLI 可能依賴）
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
}


def build_sanitized_env(project_id: Optional[int] = None) -> dict:
    """Build a sanitised environment dict: whitelist + project env vars from DB.

    Parameters
    ----------
    project_id : int, optional
        If given, also inject project-specific env vars stored in ProjectEnvVar.

    Returns
    -------
    dict
        Clean environment dict safe for subprocess.
    """
    env = {k: v for k, v in os.environ.items() if k in ALLOWED_ENV_KEYS}

    # 避免子程序偵測到巢狀 Claude session 而拒絕啟動
    env.pop("CLAUDECODE", None)

    # 從 SystemSetting 注入全域 API Keys（如 gemini_api_key）
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            for setting_key, env_key in [
                ("gemini_api_key", "GEMINI_API_KEY"),
                ("google_api_key", "GOOGLE_API_KEY"),
            ]:
                setting = session.get(SystemSetting, setting_key)
                if setting and setting.value:
                    env[env_key] = setting.value
    except Exception as e:
        logger.warning(f"[Sandbox] Failed to load SystemSetting keys: {e}")

    # 從 DB 讀取專案環境變數並注入
    if project_id:
        try:
            from sqlmodel import Session, select
            from app.database import engine
            from app.models.core import ProjectEnvVar
            with Session(engine) as session:
                env_vars = session.exec(
                    select(ProjectEnvVar).where(ProjectEnvVar.project_id == project_id)
                ).all()
                for v in env_vars:
                    env[v.key] = v.value
        except Exception as e:
            logger.warning(f"[Sandbox] Failed to load project env vars: {e}")

    return env


def get_popen_kwargs(
    landlock_paths: Optional[dict] = None,
) -> dict:
    """Return platform-specific Popen kwargs for process isolation.

    - Linux/macOS: start_new_session=True (new process group)
    - Linux with aegis-sandbox user: setuid/setgid
    - Linux with Landlock: filesystem access restriction
    - Windows: CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    Parameters
    ----------
    landlock_paths : dict, optional
        If provided, apply Landlock filesystem restrictions.
        Keys: ``allowed_read`` (list[str]), ``allowed_rw`` (list[str]).
        Ignored on non-Linux or when Landlock is unavailable.
    """
    system = platform.system()
    kwargs: dict = {}

    if system in ("Linux", "Darwin"):
        kwargs["start_new_session"] = True

        # Linux: 嘗試以 aegis-sandbox 使用者身分執行
        if system == "Linux":
            try:
                import pwd
                pw = pwd.getpwnam("aegis-sandbox")
                kwargs["preexec_fn"] = _make_preexec(pw.pw_uid, pw.pw_gid)
                logger.info("[Sandbox] Will run as aegis-sandbox user")
            except (KeyError, ImportError):
                pass  # 使用者不存在或非 Linux，fallback 無隔離

        # Landlock filesystem restriction (Linux only, kernel >= 5.13)
        if system == "Linux" and landlock_paths is not None:
            try:
                from app.core.sandbox_kernel import LandlockSandbox

                sandbox = LandlockSandbox()
                sandbox.restrict_paths(
                    allowed_read=landlock_paths.get("allowed_read", []),
                    allowed_rw=landlock_paths.get("allowed_rw", []),
                )
                existing_preexec = kwargs.get("preexec_fn")
                landlock_preexec = sandbox.apply_to_preexec(existing_preexec)
                if landlock_preexec is not None:
                    kwargs["preexec_fn"] = landlock_preexec
                    logger.info("[Sandbox] Landlock filesystem restriction configured")
            except Exception as e:
                logger.warning(f"[Sandbox] Landlock setup failed: {e}")

    elif system == "Windows":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )

    return kwargs


def _make_preexec(uid: int, gid: int):
    """Create a preexec_fn that switches to the sandbox user."""
    def _preexec():
        os.setgid(gid)
        os.setuid(uid)
    return _preexec
