"""多帳號管理核心邏輯：profiles 讀寫、帳號切換、最佳帳號選擇"""
import json
import shutil
import logging
import subprocess
import re
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from sqlmodel import Session, select

from app.models.core import Account, Member, MemberAccount
from app.core.claude_usage import _read_token, _fetch_usage
from app.core.gemini_usage import get_gemini_quota, _get_access_token

logger = logging.getLogger(__name__)

# 暫存進行中的認證 session（key = session_id, value = subprocess.Popen）
_pending_auth_sessions: Dict[str, subprocess.Popen] = {}

# Profiles 目錄
CLAUDE_PROFILES_DIR = Path.home() / ".claude-profiles"
GEMINI_PROFILES_DIR = Path.home() / ".gemini-profiles"
# TODO: Codex profiles 目錄待確認
CODEX_PROFILES_DIR = Path.home() / ".codex-profiles"

# 活躍 credential 位置
CLAUDE_CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
GEMINI_CREDS_FILE = Path.home() / ".gemini" / "oauth_creds.json"
# TODO: Codex credential 位置待確認
CODEX_CREDS_FILE = Path.home() / ".codex" / "credentials.json"


def ensure_profiles_dirs():
    """確保 profiles 目錄存在"""
    CLAUDE_PROFILES_DIR.mkdir(exist_ok=True)
    GEMINI_PROFILES_DIR.mkdir(exist_ok=True)
    CODEX_PROFILES_DIR.mkdir(exist_ok=True)


def capture_current_credential(provider: str, profile_name: str) -> Optional[str]:
    """從目前 CLI 登入狀態捕捉 credential，存為 profile 檔案。回傳檔名。"""
    ensure_profiles_dirs()

    if provider == "claude":
        src = CLAUDE_CREDS_FILE
        dst_dir = CLAUDE_PROFILES_DIR
    elif provider == "gemini":
        src = GEMINI_CREDS_FILE
        dst_dir = GEMINI_PROFILES_DIR
    elif provider == "codex":
        # TODO: Codex credential 位置待確認
        src = CODEX_CREDS_FILE
        dst_dir = CODEX_PROFILES_DIR
    elif provider == "ollama":
        # Ollama 是本地運行，不需要 credential
        return None
    else:
        return None

    if not src.exists():
        return None

    filename = f"{profile_name}.json"
    dst = dst_dir / filename
    shutil.copy2(src, dst)
    logger.info(f"Captured {provider} credential to {dst}")
    return filename


def activate_account(account: Account):
    """啟用指定帳號：將 profile 複製到活躍 credential 位置"""
    if account.provider == "claude":
        src = CLAUDE_PROFILES_DIR / account.credential_file
        dst = CLAUDE_CREDS_FILE
    elif account.provider == "gemini":
        src = GEMINI_PROFILES_DIR / account.credential_file
        dst = GEMINI_CREDS_FILE
    elif account.provider == "codex":
        # TODO: Codex credential 位置待確認
        src = CODEX_PROFILES_DIR / account.credential_file
        dst = CODEX_CREDS_FILE
    elif account.provider == "ollama":
        # Ollama 本地運行，不需要啟用帳號
        logger.info(f"Ollama runs locally, no account activation needed")
        return
    else:
        return

    if not src.exists():
        logger.warning(f"Profile file not found: {src}")
        return

    shutil.copy2(src, dst)
    logger.info(f"Activated {account.provider} account: {account.name} ({account.credential_file})")


def get_account_email(provider: str, credential_file: str) -> str:
    """從 credential 檔案讀取 email"""
    if provider == "claude":
        filepath = CLAUDE_PROFILES_DIR / credential_file
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("claudeAiOauth", {}).get("email", "")
        except Exception:
            return ""
    elif provider == "gemini":
        # Gemini 的 email 在 google_accounts.json
        accounts_file = Path.home() / ".gemini" / "google_accounts.json"
        try:
            if accounts_file.exists():
                with open(accounts_file, encoding="utf-8") as f:
                    acc = json.load(f)
                if isinstance(acc, dict):
                    return acc.get("active", "")
            return ""
        except Exception:
            return ""
    return ""


def get_subscription_type(provider: str, credential_file: str) -> str:
    """從 credential 檔案讀取訂閱類型"""
    if provider == "claude":
        filepath = CLAUDE_PROFILES_DIR / credential_file
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            oauth = data.get("claudeAiOauth", {})
            return oauth.get("subscriptionType", oauth.get("rateLimitTier", "unknown"))
        except Exception:
            return "unknown"
    elif provider == "gemini":
        return "ai-pro"  # 目前 Gemini CLI 都是 Google One AI Pro
    return "unknown"


def get_member_with_accounts(session: Session, member_id: int) -> Optional[Dict[str, Any]]:
    """取得成員及其綁定帳號"""
    member = session.get(Member, member_id)
    if not member:
        return None

    bindings = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id)
        .order_by(MemberAccount.priority)
    ).all()

    accounts = []
    for b in bindings:
        account = session.get(Account, b.account_id)
        if account:
            accounts.append({
                "account_id": account.id,
                "priority": b.priority,
                "model": b.model,
                "name": account.name,
                "provider": account.provider,
                "is_healthy": account.is_healthy,
            })

    return {
        **member.model_dump(),
        "accounts": accounts,
    }


def select_best_account(session: Session, member_id: int) -> Optional[Account]:
    """根據成員的帳號池，選擇最佳可用帳號"""
    bindings = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id)
        .order_by(MemberAccount.priority)
    ).all()

    for binding in bindings:
        account = session.get(Account, binding.account_id)
        if not account or not account.is_healthy:
            continue

        if account.provider == "claude":
            # 啟用此帳號後查用量
            activate_account(account)
            token = _read_token(CLAUDE_CREDS_FILE)
            if token:
                # 使用帳號名稱作為 cache_key 避免 429
                usage = _fetch_usage(token, cache_key=account.name or "default")
                if usage:
                    five_hour = usage.get("five_hour", {}).get("utilization", 100)
                    if five_hour < 80:
                        return account

        elif account.provider == "gemini":
            # Gemini 用共用 credential 查詢
            activate_account(account)
            quota = get_gemini_quota()
            if quota:
                target_model = binding.model or "gemini-2.5-flash"
                # 尋找匹配的模型配額
                for model_key, info in quota.items():
                    if target_model.replace("-", "") in model_key.replace("-", ""):
                        if info.get("remaining", 0) > 10:
                            return account
                        break
                else:
                    # 沒找到特定模型，只要有任何模型有配額就可用
                    return account

        elif account.provider == "codex":
            # TODO: Codex 帳號健康檢查待實作
            # 目前假設已登入的帳號都可用
            activate_account(account)
            return account

        elif account.provider == "ollama":
            # Ollama 本地運行，檢查服務是否可用
            try:
                result = subprocess.run(
                    ["ollama", "list"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return account
            except Exception:
                pass

    return None


# ==========================================
# Guided CLI Login (引導式 CLI 登入)
# ==========================================
def start_gcloud_auth() -> Tuple[str, str]:
    """
    啟動 gcloud auth application-default login --no-browser
    回傳 (session_id, auth_url)
    """
    import uuid
    import select
    session_id = uuid.uuid4().hex

    try:
        # 使用 echo Y 自動回答 GCP VM 上的確認問題
        proc = subprocess.Popen(
            "echo Y | gcloud auth application-default login --no-launch-browser",
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # 讀取輸出直到找到 URL（最多等 15 秒）
        auth_url = ""
        output_lines = []
        import time
        start_time = time.time()

        while time.time() - start_time < 15:
            line = proc.stdout.readline()
            if not line:
                break
            output_lines.append(line)

            # 找 URL
            url_match = re.search(r'https://accounts\.google\.com/[^\s]+', line)
            if url_match:
                auth_url = url_match.group(0)
                break

        if not auth_url:
            proc.terminate()
            raise Exception(f"找不到授權 URL。輸出：{''.join(output_lines)}")

        # 保存 session
        _pending_auth_sessions[session_id] = proc
        logger.info(f"Started gcloud auth session: {session_id}")

        return session_id, auth_url

    except FileNotFoundError:
        raise Exception("找不到 gcloud CLI。請先安裝 Google Cloud SDK。")
    except Exception as e:
        raise Exception(f"啟動認證失敗：{str(e)}")


def complete_gcloud_auth(session_id: str, auth_code: str) -> bool:
    """
    完成 gcloud auth：將授權碼輸入到等待中的 process
    """
    proc = _pending_auth_sessions.get(session_id)
    if not proc:
        raise Exception("找不到此認證 session。可能已過期，請重新開始。")

    try:
        # 寫入授權碼
        proc.stdin.write(auth_code + "\n")
        proc.stdin.flush()

        # 等待完成
        stdout, _ = proc.communicate(timeout=30)

        # 清理
        del _pending_auth_sessions[session_id]

        if proc.returncode == 0:
            logger.info(f"gcloud auth completed for session: {session_id}")
            return True
        else:
            raise Exception(f"認證失敗（返回碼 {proc.returncode}）：{stdout}")

    except subprocess.TimeoutExpired:
        proc.terminate()
        del _pending_auth_sessions[session_id]
        raise Exception("認證超時。請重試。")
    except Exception as e:
        if session_id in _pending_auth_sessions:
            del _pending_auth_sessions[session_id]
        raise


def cancel_gcloud_auth(session_id: str):
    """取消進行中的認證"""
    proc = _pending_auth_sessions.get(session_id)
    if proc:
        proc.terminate()
        del _pending_auth_sessions[session_id]
        logger.info(f"Cancelled gcloud auth session: {session_id}")


def check_gcloud_status() -> Dict[str, Any]:
    """檢查 gcloud CLI 狀態"""
    result = {
        "installed": False,
        "version": None,
        "authenticated": False,
        "account": None,
    }

    # 檢查是否安裝 (Windows 需要 shell=True)
    try:
        ver_result = subprocess.run(
            "gcloud --version",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if ver_result.returncode == 0:
            result["installed"] = True
            # 取第一行作為版本
            lines = ver_result.stdout.strip().split("\n")
            if lines:
                result["version"] = lines[0]
    except Exception:
        pass

    # 檢查認證狀態
    try:
        auth_result = subprocess.run(
            "gcloud auth list --format=json",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if auth_result.returncode == 0:
            accounts = json.loads(auth_result.stdout)
            if accounts:
                result["authenticated"] = True
                # 找 active account
                for acc in accounts:
                    if acc.get("status") == "ACTIVE":
                        result["account"] = acc.get("account")
                        break
    except Exception:
        pass

    return result


# ==========================================
# Claude Auth Status (Claude 認證狀態)
# ==========================================
def check_claude_status() -> Dict[str, Any]:
    """檢查 Claude CLI 狀態和 token 過期時間"""
    from datetime import datetime
    result = {
        "installed": False,
        "version": None,
        "authenticated": False,
        "email": None,
        "subscription_type": None,
        "expires_at": None,
        "expired": False,
        "hours_until_expiry": None,
    }

    # 檢查是否安裝
    try:
        ver_result = subprocess.run(
            "claude --version",
            shell=True, capture_output=True, text=True, timeout=10
        )
        if ver_result.returncode == 0:
            result["installed"] = True
            result["version"] = ver_result.stdout.strip()
    except Exception:
        pass

    # 檢查 credentials 檔案
    if CLAUDE_CREDS_FILE.exists():
        try:
            with open(CLAUDE_CREDS_FILE, encoding="utf-8") as f:
                creds = json.load(f)
            oauth = creds.get("claudeAiOauth", {})

            if oauth.get("accessToken"):
                result["authenticated"] = True
                result["email"] = oauth.get("email")
                result["subscription_type"] = oauth.get("subscriptionType")

                # 檢查過期時間（毫秒時間戳）
                expires_at_ms = oauth.get("expiresAt", 0)
                if expires_at_ms:
                    expires_at = datetime.fromtimestamp(expires_at_ms / 1000)
                    now = datetime.now()
                    result["expires_at"] = expires_at.isoformat()
                    result["expired"] = expires_at < now
                    hours = (expires_at - now).total_seconds() / 3600
                    result["hours_until_expiry"] = round(hours, 2)
        except Exception as e:
            logger.warning(f"Failed to read Claude credentials: {e}")

    return result


def update_claude_credentials(credentials_json: str) -> bool:
    """更新 Claude credentials 檔案"""
    try:
        # 驗證 JSON 格式
        creds = json.loads(credentials_json)
        if "claudeAiOauth" not in creds:
            raise ValueError("Invalid credentials format: missing claudeAiOauth")

        # 確保目錄存在
        CLAUDE_CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 寫入檔案
        with open(CLAUDE_CREDS_FILE, "w", encoding="utf-8") as f:
            json.dump(creds, f, indent=2)

        logger.info("Claude credentials updated successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to update Claude credentials: {e}")
        raise Exception(f"更新 credentials 失敗：{str(e)}")


# 暫存進行中的 Claude 認證 session
_pending_claude_sessions: Dict[str, Dict] = {}


def start_claude_auth() -> Tuple[str, str]:
    """
    啟動 Claude setup-token 引導式登入
    使用 pty 模組提供 pseudo-TTY
    回傳 (session_id, auth_url)
    """
    import uuid
    import pty
    import os
    import select
    import time

    session_id = uuid.uuid4().hex

    try:
        # 建立 pseudo-terminal
        master, slave = pty.openpty()

        # 執行 claude setup-token
        proc = subprocess.Popen(
            ["/usr/local/bin/claude", "setup-token"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env={**os.environ, "HOME": str(Path.home()), "TERM": "xterm-256color"},
        )

        os.close(slave)

        # 讀取輸出直到找到 URL（最多等 20 秒）
        auth_url = ""
        output = []
        start_time = time.time()

        while time.time() - start_time < 20:
            if select.select([master], [], [], 0.5)[0]:
                try:
                    data = os.read(master, 4096)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        output.append(text)

                        # 找 Claude OAuth URL
                        url_match = re.search(r"https://claude\.ai/oauth/authorize\?[^\s\x1b]+", text)
                        if url_match:
                            auth_url = url_match.group(0)
                            break
                except OSError:
                    break
            if proc.poll() is not None:
                break

        if not auth_url:
            os.close(master)
            proc.terminate()
            raise Exception(f"找不到授權 URL。輸出：{''.join(output)[-500:]}")

        # 保存 session（包含 master fd 和 process）
        _pending_claude_sessions[session_id] = {
            "master": master,
            "proc": proc,
        }
        logger.info(f"Started Claude auth session: {session_id}")

        return session_id, auth_url

    except FileNotFoundError:
        raise Exception("找不到 Claude CLI。請先安裝 Claude Code。")
    except Exception as e:
        raise Exception(f"啟動認證失敗：{str(e)}")


def complete_claude_auth(session_id: str, auth_code: str) -> bool:
    """
    完成 Claude 認證：將授權碼輸入到等待中的 process
    """
    import os
    import time
    import select

    session = _pending_claude_sessions.get(session_id)
    if not session:
        raise Exception("找不到此認證 session。可能已過期，請重新開始。")

    master = session["master"]
    proc = session["proc"]

    try:
        # 寫入授權碼
        os.write(master, (auth_code + "\n").encode())

        # 等待完成（最多 30 秒）
        output = []
        start_time = time.time()

        while time.time() - start_time < 30:
            if select.select([master], [], [], 0.5)[0]:
                try:
                    data = os.read(master, 4096)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        output.append(text)
                        # 檢查成功訊息
                        if "successfully" in text.lower() or "token" in text.lower():
                            break
                except OSError:
                    break
            if proc.poll() is not None:
                break

        # 清理
        os.close(master)
        proc.wait(timeout=5)
        del _pending_claude_sessions[session_id]

        if proc.returncode == 0:
            logger.info(f"Claude auth completed for session: {session_id}")
            return True
        else:
            raise Exception(f"認證失敗（返回碼 {proc.returncode}）")

    except subprocess.TimeoutExpired:
        proc.terminate()
        del _pending_claude_sessions[session_id]
        raise Exception("認證超時。請重試。")
    except Exception as e:
        if session_id in _pending_claude_sessions:
            try:
                os.close(master)
                proc.terminate()
            except:
                pass
            del _pending_claude_sessions[session_id]
        raise


def cancel_claude_auth(session_id: str):
    """取消進行中的 Claude 認證"""
    import os

    session = _pending_claude_sessions.get(session_id)
    if session:
        try:
            os.close(session["master"])
            session["proc"].terminate()
        except:
            pass
        del _pending_claude_sessions[session_id]
        logger.info(f"Cancelled Claude auth session: {session_id}")
