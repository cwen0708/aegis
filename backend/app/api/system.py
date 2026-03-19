from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.database import get_session
from app.models.core import SystemSetting
from app.core.usage_poller import get_cached_claude_usage, get_cached_gemini_usage, get_last_updated
from app.core.default_office_layout import get_default_office_layout_json
import app.core.cron_poller as cron_module
from app.core.ws_manager import websocket_clients
import json as json_module
import os
import time as time_module
import subprocess

router = APIRouter(tags=["system"])


# ==========================================
# Claude Usage
# ==========================================
@router.get("/claude/usage")
def claude_usage():
    """回傳快取的 Claude 帳號用量（由 usage_poller 每 120 秒更新）"""
    return {"accounts": get_cached_claude_usage(), "updated_at": get_last_updated()}


@router.get("/gemini/usage")
def gemini_usage():
    """回傳快取的 Gemini 配額（由 usage_poller 每 120 秒更新）"""
    return {**get_cached_gemini_usage(), "updated_at": get_last_updated()}


# ==========================================
# Service Health
# ==========================================
_services_cache: dict = {"data": None, "ts": 0}
_CACHE_TTL = 10  # seconds


def _check_claude_cli() -> dict:
    info = {"installed": False, "version": None, "authenticated": False, "account": None, "subscription": None}
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            info["installed"] = True
            info["version"] = result.stdout.strip()
    except Exception:
        pass

    # Check credentials
    creds_path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    try:
        if os.path.exists(creds_path):
            with open(creds_path, encoding="utf-8") as f:
                creds = json_module.load(f)
            if creds:
                info["authenticated"] = True
    except Exception:
        pass

    # Check profiles for account info
    profiles_dir = os.path.join(os.path.expanduser("~"), ".claude-profiles")
    try:
        if os.path.isdir(profiles_dir):
            for fname in os.listdir(profiles_dir):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(profiles_dir, fname), encoding="utf-8") as f:
                            profile = json_module.load(f)
                        info["account"] = fname.replace(".json", "")
                        info["subscription"] = profile.get("subscriptionType", profile.get("subscription_type"))
                    except Exception:
                        pass
                    break
        if not info["account"] and info["authenticated"]:
            info["account"] = "default"
    except Exception:
        pass

    return info


def _check_gemini_cli() -> dict:
    info = {"installed": False, "version": None, "authenticated": False, "account": None}
    try:
        result = subprocess.run(
            ["npm", "list", "-g", "@google/gemini-cli", "--json"],
            capture_output=True, text=True, timeout=5, shell=True
        )
        if result.returncode == 0:
            data = json_module.loads(result.stdout)
            deps = data.get("dependencies", {})
            gemini = deps.get("@google/gemini-cli", {})
            if gemini:
                info["installed"] = True
                info["version"] = gemini.get("version", "unknown")
    except Exception:
        pass

    # Check Google account
    accounts_path = os.path.join(os.path.expanduser("~"), ".gemini", "google_accounts.json")
    try:
        if os.path.exists(accounts_path):
            with open(accounts_path, encoding="utf-8") as f:
                accounts = json_module.load(f)
            if accounts:
                info["authenticated"] = True
                if isinstance(accounts, list) and len(accounts) > 0:
                    first = accounts[0]
                    info["account"] = first.get("email") or first.get("account") or str(first)
                elif isinstance(accounts, dict):
                    info["account"] = next(iter(accounts), None)
    except Exception:
        pass

    # Fallback: check oauth creds
    if not info["authenticated"]:
        oauth_path = os.path.join(os.path.expanduser("~"), ".gemini", "oauth_creds.json")
        try:
            if os.path.exists(oauth_path):
                info["authenticated"] = True
        except Exception:
            pass

    return info


@router.get("/system/services")
def get_services(session: Session = Depends(get_session)):
    """查詢所有服務健康狀態（引擎 + CLI 工具，10 秒快取）"""
    now = time_module.time()
    if _services_cache["data"] and (now - _services_cache["ts"]) < _CACHE_TTL:
        return _services_cache["data"]

    # 讀取 Worker 暫停旗標
    paused_setting = session.get(SystemSetting, "worker_paused")
    worker_paused = paused_setting and paused_setting.value == "true"

    # 偵測 Worker 獨立程序的 PID
    worker_pid = None
    worker_status = "stopped"
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                cmd_str = ' '.join(cmdline)
                if 'worker.py' in cmd_str and 'python' in cmd_str.lower():
                    worker_pid = proc.info['pid']
                    worker_status = "paused" if worker_paused else "running"
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        # psutil 不可用時 fallback：假設 systemd 管理，無法偵測 PID
        worker_status = "paused" if worker_paused else "unknown"

    if not worker_pid and not worker_paused:
        worker_status = "stopped"

    result = {
        "pid": os.getpid(),
        "engines": {
            "task_worker": {
                "status": worker_status,
                "pid": worker_pid,
                "interval_sec": 3,
                "is_paused": worker_paused,
            },
            "cron_poller": {
                "status": "running",
                "interval_sec": 60,
                "paused_projects": list(cron_module.paused_projects),
                "last_check": cron_module.last_check_at,
            },
            "websocket": {
                "status": "running",
                "clients": len(websocket_clients),
            },
        },
        "cli_tools": {
            "claude": _check_claude_cli(),
            "gemini": _check_gemini_cli(),
        },
    }

    _services_cache["data"] = result
    _services_cache["ts"] = now
    return result


# ==========================================
# System Settings
# ==========================================
SETTING_DEFAULTS = {
    "timezone": "Asia/Taipei",
    "max_workstations": "3",
    "office_layout": get_default_office_layout_json(),
}


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    """回傳所有設定（合併預設值）"""
    result = dict(SETTING_DEFAULTS)
    db_keys = set()
    rows = session.exec(select(SystemSetting)).all()
    for row in rows:
        result[row.key] = row.value
        db_keys.add(row.key)
    # 向下相容：只在 DB 沒有 max_workstations 時才用舊 key
    if "max_workstations" not in db_keys and "max_concurrent_agents" in db_keys:
        result["max_workstations"] = result["max_concurrent_agents"]
    result.pop("max_concurrent_agents", None)
    # Mask 敏感 token（只顯示後 4 位）
    for secret_key in ("github_pat",):
        if secret_key in result and result[secret_key]:
            val = result[secret_key]
            result[secret_key] = f"***{val[-4:]}" if len(val) > 4 else "***"
    return result


@router.put("/settings")
def update_settings(data: dict, session: Session = Depends(get_session)):
    """批次更新設定"""
    for key, value in data.items():
        existing = session.get(SystemSetting, key)
        if existing:
            existing.value = str(value)
            session.add(existing)
        else:
            session.add(SystemSetting(key=key, value=str(value)))
    session.commit()
    # 工作台數量已寫入 DB，Worker 下次 poll 時會自動讀取
    if "max_workstations" in data:
        try:
            val = int(data["max_workstations"])
            if val < 1 or val > 100:
                raise HTTPException(status_code=400, detail="max_workstations 必須介於 1~100")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="max_workstations 必須為正整數")
    return get_settings(session=session)
