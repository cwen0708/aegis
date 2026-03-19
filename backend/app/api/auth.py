"""Auth & CLI Management API — admin auth, Claude/Gcloud auth, CLI install"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from app.database import get_session
from app.models.core import SystemSetting, Account
from app.core.account_manager import (
    check_claude_status, update_claude_credentials,
    start_claude_auth, complete_claude_auth, cancel_claude_auth,
    check_gcloud_status, start_gcloud_auth, complete_gcloud_auth, cancel_gcloud_auth,
)
import subprocess
import os
from pathlib import Path

router = APIRouter(tags=["auth"])


# ==========================================
# Auth API (Admin Password)
# ==========================================
class AuthVerifyRequest(BaseModel):
    password: str

class AuthChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class AuthSetInitialPasswordRequest(BaseModel):
    new_password: str


@router.post("/auth/verify")
def verify_admin_password(req: AuthVerifyRequest, session: Session = Depends(get_session)):
    """驗證管理員密碼，回傳 session token"""
    from app.core.auth import check_password, hash_password, generate_session_token, DEFAULT_PASSWORD

    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else DEFAULT_PASSWORD

    if not check_password(req.password, stored_password):
        raise HTTPException(status_code=401, detail="密碼錯誤")

    # 自動遷移：明文密碼 → scrypt 雜湊
    if not stored_password.startswith("$scrypt$"):
        hashed = hash_password(req.password)
        if setting:
            setting.value = hashed
            session.add(setting)
        else:
            session.add(SystemSetting(key="admin_password", value=hashed))
        session.commit()

    token = generate_session_token(ttl_hours=8)
    return {"success": True, "token": token, "expires_in": 28800}


@router.post("/auth/change-password")
def change_admin_password(req: AuthChangePasswordRequest, session: Session = Depends(get_session)):
    """修改管理員密碼"""
    from app.core.auth import check_password, hash_password, DEFAULT_PASSWORD

    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else DEFAULT_PASSWORD

    if not check_password(req.current_password, stored_password):
        raise HTTPException(status_code=401, detail="目前密碼錯誤")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")

    hashed = hash_password(req.new_password)
    if setting:
        setting.value = hashed
        session.add(setting)
    else:
        session.add(SystemSetting(key="admin_password", value=hashed))
    session.commit()
    return {"success": True, "message": "密碼已更新"}


# ==========================================
# User Auth (BotUser 用戶登入)
# ==========================================
class UserLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/user-login")
def user_login(req: UserLoginRequest, session: Session = Depends(get_session)):
    """用戶登入（BotUser platform=web），回傳含 user_id 的 session token"""
    from app.core.auth import check_password, generate_session_token
    from app.models.core import BotUser
    from datetime import datetime, timezone

    user = session.exec(
        select(BotUser).where(
            BotUser.platform == "web",
            BotUser.platform_user_id == req.username,
            BotUser.is_active == True,
        )
    ).first()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    if not check_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    # 檢查鎖定
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=423, detail="帳號已鎖定，請稍後再試")

    # 更新最後活躍時間
    user.last_active_at = datetime.now(timezone.utc)
    user.failed_verify_count = 0
    session.add(user)
    session.commit()

    token = generate_session_token(ttl_hours=8, user_type="user", user_id=user.id)
    return {
        "success": True,
        "token": token,
        "expires_in": 28800,
        "user": {
            "id": user.id,
            "username": user.platform_user_id,
            "display_name": user.username or user.platform_user_id,
            "level": user.level,
        },
    }


class RegisterWithInviteRequest(BaseModel):
    invite_code: str
    username: str
    password: str


@router.post("/auth/register-with-invite")
def register_with_invite(req: RegisterWithInviteRequest, session: Session = Depends(get_session)):
    """用邀請碼註冊網頁帳號：驗證邀請碼 → 建 BotUser(web) → 設密碼 → 登入"""
    from app.core.auth import hash_password, generate_session_token
    from app.models.core import BotUser, InviteCode, BotUserProject, BotUserMember
    from datetime import datetime, timezone, timedelta
    import json as json_module

    # 驗證輸入
    username = req.username.strip()
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="帳號至少 2 個字元")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少 6 個字元")

    # 檢查帳號是否已存在
    existing = session.exec(
        select(BotUser).where(BotUser.platform == "web", BotUser.platform_user_id == username)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="此帳號已被使用")

    # 驗證邀請碼
    invite = session.exec(
        select(InviteCode).where(InviteCode.code == req.invite_code)
    ).first()
    if not invite:
        raise HTTPException(status_code=400, detail="無效的邀請碼")
    if invite.expires_at:
        exp = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="邀請碼已過期")
    if invite.used_count >= invite.max_uses:
        raise HTTPException(status_code=400, detail="邀請碼已達使用上限")

    # 建立 BotUser
    now = datetime.now(timezone.utc)
    user = BotUser(
        platform="web",
        platform_user_id=username,
        username=invite.user_display_name or username,
        level=invite.target_level,
        is_active=True,
        password_hash=hash_password(req.password),
        created_at=now,
        last_active_at=now,
    )
    if invite.target_member_id:
        user.default_member_id = invite.target_member_id
    if invite.access_valid_days:
        user.access_expires_at = now + timedelta(days=invite.access_valid_days)

    session.add(user)
    session.flush()  # 取得 user.id

    # 跨平台綁定：如果邀請碼已有 owner_person_id，綁定到同一個 person
    if invite.owner_person_id:
        user.person_id = invite.owner_person_id
    else:
        user.person_id = user.id
        invite.owner_person_id = user.person_id

    # 建立 BotUserMember
    if invite.target_member_id:
        session.add(BotUserMember(
            bot_user_id=user.id,
            member_id=invite.target_member_id,
            is_default=True,
        ))

    # 建立專案權限
    if invite.allowed_projects:
        try:
            project_ids = json_module.loads(invite.allowed_projects)
            for idx, pid in enumerate(project_ids):
                session.add(BotUserProject(
                    bot_user_id=user.id,
                    project_id=pid,
                    display_name=invite.user_display_name,
                    description=invite.user_description,
                    can_view=invite.default_can_view,
                    can_create_card=invite.default_can_create_card,
                    can_run_task=invite.default_can_run_task,
                    can_access_sensitive=invite.default_can_access_sensitive,
                    is_default=(idx == 0),
                ))
        except (json_module.JSONDecodeError, TypeError):
            pass

    # 更新邀請碼使用次數
    invite.used_count += 1
    session.commit()

    # 直接登入
    token = generate_session_token(ttl_hours=8, user_type="user", user_id=user.id)
    return {
        "success": True,
        "token": token,
        "expires_in": 28800,
        "user": {
            "id": user.id,
            "username": user.platform_user_id,
            "display_name": user.username or user.platform_user_id,
            "level": user.level,
        },
        "message": f"註冊成功！身份：{'管理員' if user.level >= 3 else '成員' if user.level >= 2 else '訪客'}",
    }


@router.get("/auth/me")
def get_current_user(request_obj=Depends(lambda request: request), session: Session = Depends(get_session)):
    """根據 token 取得當前用戶資訊"""
    from app.core.auth import decode_session_token
    from app.models.core import BotUser, BotUserProject, Project

    auth_header = request_obj.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    payload = decode_session_token(token) if token else None

    if not payload:
        return {"authenticated": False}

    if payload["type"] == "admin":
        return {"authenticated": True, "type": "admin", "projects": None}

    # user token → 查 BotUser 和授權專案
    user = session.get(BotUser, payload["uid"])
    if not user:
        return {"authenticated": False}

    projects = session.exec(
        select(BotUserProject).where(
            BotUserProject.bot_user_id == user.id,
            BotUserProject.can_view == True,
        )
    ).all()
    project_ids = [p.project_id for p in projects]

    return {
        "authenticated": True,
        "type": "user",
        "user": {
            "id": user.id,
            "username": user.platform_user_id,
            "display_name": user.username or user.platform_user_id,
            "level": user.level,
        },
        "project_ids": project_ids,
    }


@router.get("/auth/password-status")
def get_password_status(session: Session = Depends(get_session)):
    """檢查密碼是否仍為預設值"""
    from app.core.auth import check_password, DEFAULT_PASSWORD

    default_password = DEFAULT_PASSWORD
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else default_password

    is_default = check_password(default_password, stored_password)
    return {"is_default": is_default}


@router.post("/auth/set-initial-password")
def set_initial_password(req: AuthSetInitialPasswordRequest, session: Session = Depends(get_session)):
    """首次設定密碼（僅在密碼仍為預設值時可用）"""
    from app.core.auth import check_password, hash_password, DEFAULT_PASSWORD

    default_password = DEFAULT_PASSWORD
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else default_password

    if not check_password(default_password, stored_password):
        raise HTTPException(status_code=403, detail="密碼已被修改，請使用一般修改密碼功能")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")

    hashed = hash_password(req.new_password)
    if setting:
        setting.value = hashed
        session.add(setting)
    else:
        session.add(SystemSetting(key="admin_password", value=hashed))
    session.commit()
    return {"success": True, "message": "密碼已設定"}


# ==========================================
# Claude Auth (Claude 認證)
# ==========================================
# 注意：/claude/status 和 /claude/credentials 在 routes.py 中重複定義了兩次，
# 這裡只保留最後一個版本（行 3095-3116）。

@router.get("/claude/status")
def get_claude_status():
    """檢查 Claude CLI 狀態和 token 過期時間"""
    return check_claude_status()


class ClaudeCredentialsRequest(BaseModel):
    credentials: str  # JSON string


@router.post("/claude/credentials")
def update_claude_credentials_api(data: ClaudeCredentialsRequest):
    """更新 Claude credentials 檔案（從其他機器同步）"""
    try:
        update_claude_credentials(data.credentials)
        return {"ok": True, "message": "Credentials 已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ClaudeTokenRequest(BaseModel):
    token: str


@router.post("/claude/token")
def save_claude_token(data: ClaudeTokenRequest):
    """
    儲存 Claude OAuth Token（長期 token，1 年有效）
    用戶在本地執行 `claude setup-token` 取得 token 後貼上
    """
    import time
    token = data.token.strip()
    if not token.startswith("sk-ant-oat01-"):
        raise HTTPException(status_code=400, detail="無效的 Token 格式。Token 應以 sk-ant-oat01- 開頭。")

    # 儲存到 .env 檔案
    env_file = Path(__file__).parent.parent.parent / ".env"
    env_content = ""
    if env_file.exists():
        env_content = env_file.read_text()

    # 記錄設定時間（Unix 時間戳，毫秒）
    token_set_at = int(time.time() * 1000)

    # 更新或新增 CLAUDE_CODE_OAUTH_TOKEN 和 CLAUDE_CODE_OAUTH_TOKEN_SET_AT
    lines = env_content.strip().split("\n") if env_content.strip() else []
    new_lines = [line for line in lines if not line.startswith("CLAUDE_CODE_OAUTH_TOKEN")]
    new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN={token}")
    new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN_SET_AT={token_set_at}")
    env_file.write_text("\n".join(new_lines) + "\n")

    # 同時設定到環境變數（讓當前進程立即生效）
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    os.environ["CLAUDE_CODE_OAUTH_TOKEN_SET_AT"] = str(token_set_at)

    return {"ok": True, "message": "Token 已儲存！請重啟 Worker 服務使其生效。"}


@router.post("/claude/auth/init")
def init_claude_auth():
    """啟動 Claude 引導式登入，回傳授權 URL"""
    try:
        session_id, auth_url = start_claude_auth()
        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "instructions": [
                "1. 點擊上方連結在瀏覽器開啟",
                "2. 使用 Claude 帳號登入並授權",
                "3. 複製頁面顯示的授權碼",
                "4. 將授權碼貼到下方完成登入",
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ClaudeAuthCompleteRequest(BaseModel):
    session_id: str
    auth_code: str


@router.post("/claude/auth/complete")
def complete_claude_auth_api(data: ClaudeAuthCompleteRequest):
    """完成 Claude 引導式登入"""
    try:
        success = complete_claude_auth(data.session_id, data.auth_code)
        if not success:
            raise HTTPException(status_code=400, detail="登入失敗")
        return {"ok": True, "message": "登入成功！長期 token 已設定。"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ClaudeAuthCancelRequest(BaseModel):
    session_id: str


@router.post("/claude/auth/cancel")
def cancel_claude_auth_api(data: ClaudeAuthCancelRequest):
    """取消 Claude 引導式登入"""
    cancel_claude_auth(data.session_id)
    return {"ok": True}


# ==========================================
# Gcloud Auth (引導式 CLI 登入)
# ==========================================
@router.get("/gcloud/status")
def get_gcloud_status():
    """檢查 gcloud CLI 狀態"""
    return check_gcloud_status()


@router.post("/gcloud/auth/init")
def init_gcloud_auth():
    """啟動 gcloud 引導式登入，回傳授權 URL"""
    try:
        session_id, auth_url = start_gcloud_auth()
        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "instructions": [
                "1. 在您的瀏覽器開啟上方的授權網址",
                "2. 使用 Google 帳號登入並授權存取",
                "3. 複製 Google 給您的授權碼",
                "4. 將授權碼貼到下方輸入框完成登入",
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GcloudAuthCompleteRequest(BaseModel):
    session_id: str
    auth_code: str


@router.post("/gcloud/auth/complete")
def complete_gcloud_auth_api(data: GcloudAuthCompleteRequest, session: Session = Depends(get_session)):
    """完成 gcloud 引導式登入，並自動建立 Gemini 帳號"""
    try:
        success = complete_gcloud_auth(data.session_id, data.auth_code)
        if not success:
            raise HTTPException(status_code=400, detail="登入失敗")

        # 取得認證的 email
        status = check_gcloud_status()
        email = status.get("account", "")
        if not email:
            return {"ok": True, "message": "登入成功，但無法取得帳號資訊"}

        # 檢查是否已存在此 email 的 Gemini 帳號
        existing = session.exec(
            select(Account).where(Account.provider == "gemini", Account.email == email)
        ).first()

        if existing:
            # 更新健康狀態
            existing.is_healthy = True
            session.add(existing)
            session.commit()
            return {"ok": True, "message": f"帳號 {email} 已更新", "account_id": existing.id}

        # 建立新的 Gemini 帳號
        # credential_file 指向 gcloud 的 application_default_credentials
        new_account = Account(
            provider="gemini",
            name=email.split("@")[0],  # 用 email 前綴當名稱
            credential_file="application_default_credentials.json",
            subscription="gcloud",
            email=email,
            is_healthy=True,
        )
        session.add(new_account)
        session.commit()
        session.refresh(new_account)

        return {"ok": True, "message": f"已建立 Gemini 帳號：{email}", "account_id": new_account.id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GcloudAuthCancelRequest(BaseModel):
    session_id: str


@router.post("/gcloud/auth/cancel")
def cancel_gcloud_auth_api(data: GcloudAuthCancelRequest):
    """取消 gcloud 引導式登入"""
    cancel_gcloud_auth(data.session_id)
    return {"ok": True}


# ==========================================
# CLI Management
# ==========================================
@router.get("/cli/status")
def get_cli_status():
    """檢查 AI CLI 工具安裝狀態"""
    import shutil

    result = {
        "claude": {"installed": False, "version": None, "path": None},
        "gemini": {"installed": False, "version": None, "path": None},
        "codex": {"installed": False, "version": None, "path": None},
        "ollama": {"installed": False, "version": None, "path": None},
    }

    # 檢查 Claude CLI（使用跨平台的 shutil.which）
    try:
        claude_path = shutil.which("claude")
        if claude_path:
            result["claude"]["installed"] = True
            result["claude"]["path"] = claude_path
            # 取得版本
            ver_result = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["claude"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Gemini CLI（Windows 的 .cmd 需要 shell=True）
    try:
        gemini_path = shutil.which("gemini")
        if gemini_path:
            result["gemini"]["installed"] = True
            result["gemini"]["path"] = gemini_path
            # 取得版本（Windows .cmd 需要 shell=True）
            ver_result = subprocess.run(
                "gemini --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["gemini"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Codex CLI (OpenAI)
    try:
        codex_path = shutil.which("codex")
        if codex_path:
            result["codex"]["installed"] = True
            result["codex"]["path"] = codex_path
            # 取得版本（Windows .cmd 需要 shell=True）
            ver_result = subprocess.run(
                "codex --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["codex"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Ollama CLI
    try:
        ollama_path = shutil.which("ollama")
        if ollama_path:
            result["ollama"]["installed"] = True
            result["ollama"]["path"] = ollama_path
            # 取得版本
            ver_result = subprocess.run(
                ["ollama", "--version"], capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                # ollama version is 0.9.0
                result["ollama"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return result


@router.post("/cli/claude/install")
def install_claude_cli():
    """安裝 Claude CLI"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @anthropic-ai/claude-code"
        else:
            cmd = "sudo -n npm install -g @anthropic-ai/claude-code"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Claude CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cli/gemini/install")
def install_gemini_cli():
    """安裝 Gemini CLI"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @google/gemini-cli"
        else:
            cmd = "sudo -n npm install -g @google/gemini-cli"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Gemini CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cli/codex/install")
def install_codex_cli():
    """安裝 Codex CLI (OpenAI)"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @openai/codex"
        else:
            cmd = "sudo -n npm install -g @openai/codex"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Codex CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ollama/models")
def get_ollama_models():
    """取得 Ollama 已下載的模型列表"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"models": [], "error": "Ollama 未安裝或未啟動"}

        # 解析輸出格式：NAME    ID    SIZE    MODIFIED
        lines = result.stdout.strip().split("\n")
        models = []
        for line in lines[1:]:  # 跳過標題行
            parts = line.split()
            if parts:
                models.append({
                    "name": parts[0],
                    "id": parts[1] if len(parts) > 1 else "",
                    "size": parts[2] if len(parts) > 2 else "",
                })
        return {"models": models}
    except FileNotFoundError:
        return {"models": [], "error": "Ollama 未安裝"}
    except subprocess.TimeoutExpired:
        return {"models": [], "error": "查詢超時"}
    except Exception as e:
        return {"models": [], "error": str(e)}
