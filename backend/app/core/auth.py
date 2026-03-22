"""
Aegis 認證模組
支援兩種模式：
- local: 使用現有的密碼驗證（預設）
- supabase: 使用 Supabase JWT 驗證（連接 OneStack 時使用）
"""
import os
import secrets
import hashlib
import hmac
import json
import base64
import time
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Header, Request, status
from sqlmodel import Session

logger = logging.getLogger(__name__)

# 認證模式
AUTH_MODE = os.getenv("AEGIS_AUTH_MODE", "local")  # local | supabase
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# 預設密碼（統一常數，避免硬編碼散佈）
DEFAULT_PASSWORD = os.getenv("AEGIS_DEFAULT_PASSWORD", "aegis2026!")

# ==========================================
# Session Token（HMAC 簽名）
# ==========================================
_signing_secret: bytes | None = None
_signing_secret_ts: float = 0
_SIGNING_SECRET_MAX_AGE = 3600  # DB 來源快取 TTL（秒）


def _get_signing_secret() -> bytes:
    """取得 HMAC 簽名密鑰（env > DB > 自動生成）"""
    global _signing_secret, _signing_secret_ts

    # TTL 過期時重置快取，強制重新讀取
    if _signing_secret and time.time() - _signing_secret_ts > _SIGNING_SECRET_MAX_AGE:
        _signing_secret = None

    if _signing_secret:
        return _signing_secret

    # 1. 從環境變數（不需要 TTL，永不過期）
    env_secret = os.getenv("AEGIS_SESSION_SECRET")
    if env_secret:
        _signing_secret = env_secret.encode()
        _signing_secret_ts = float("inf")
        return _signing_secret

    # 2. 從 DB（或自動生成存入 DB）
    try:
        from app.models.core import SystemSetting
        from app.database import engine
        with Session(engine) as session:
            setting = session.get(SystemSetting, "session_secret")
            if setting and setting.value:
                _signing_secret = setting.value.encode()
                _signing_secret_ts = time.time()
            else:
                new_secret = secrets.token_hex(32)
                setting = SystemSetting(key="session_secret", value=new_secret)
                session.add(setting)
                session.commit()
                _signing_secret = new_secret.encode()
                _signing_secret_ts = time.time()
                logger.info("[Auth] Generated new session signing secret")
    except Exception:
        # Fallback: 產生一個不持久的隨機密鑰（每次重啟會失效）
        _signing_secret = secrets.token_bytes(32)
        _signing_secret_ts = time.time()

    return _signing_secret


def generate_session_token(ttl_hours: int = 8, user_type: str = "admin", user_id: int = 0) -> str:
    """產生 HMAC 簽名的 session token。
    user_type: "admin"（管理員）或 "user"（BotUser 用戶）
    user_id: BotUser.id（user_type="user" 時必填）
    """
    payload = json.dumps({
        "exp": int(time.time()) + ttl_hours * 3600,
        "type": user_type,
        "uid": user_id,
    })
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_signing_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str) -> bool:
    """驗證 session token 簽名與過期時間"""
    try:
        payload = decode_session_token(token)
        return payload is not None
    except Exception:
        return False


def decode_session_token(token: str) -> dict | None:
    """解碼 session token，回傳 payload dict 或 None。
    payload 包含：exp, type("admin"/"user"), uid(BotUser.id)
    """
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(_get_signing_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) <= time.time():
            return None
        # 拒絕舊格式 token（無 type 欄位），強制重新登入
        if "type" not in payload:
            return None
        return payload
    except Exception:
        return None


# ==========================================
# 密碼雜湊（scrypt，stdlib，無新依賴）
# ==========================================
_HASH_PREFIX = "$scrypt$"


def hash_password(password: str) -> str:
    """用 scrypt 雜湊密碼"""
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return f"{_HASH_PREFIX}{salt}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    """驗證密碼（支援雜湊和明文向後相容）"""
    if stored.startswith(_HASH_PREFIX):
        # scrypt hash
        try:
            _, salt, dk_hex = stored[len(_HASH_PREFIX):].split("$", 1)[0], \
                              stored[len(_HASH_PREFIX):].split("$")[0], \
                              stored[len(_HASH_PREFIX):].split("$")[1]
            dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
            return hmac.compare_digest(dk.hex(), dk_hex)
        except Exception:
            return False
    else:
        # 明文（向後相容，首次登入後會自動遷移）
        return secrets.compare_digest(password, stored)


def get_auth_mode() -> str:
    """取得當前認證模式"""
    return AUTH_MODE


def verify_local_password(password: str, session: Session) -> bool:
    """本地密碼驗證（現有邏輯）"""
    from app.models.core import SystemSetting

    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else DEFAULT_PASSWORD
    return check_password(password, stored_password)


async def verify_supabase_jwt(token: str) -> dict:
    """驗證 Supabase JWT token"""
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_JWT_SECRET not configured"
        )

    try:
        from jose import jwt, JWTError

        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}  # Supabase 不一定有 aud
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> Optional[dict]:
    """
    取得當前用戶（依認證模式）

    - local 模式：返回 None（使用 session 驗證）
    - supabase 模式：驗證 JWT 並返回用戶資訊
    """
    if AUTH_MODE == "local":
        # 本地模式不需要 JWT，使用現有的 session 機制
        return None

    # Supabase 模式
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format"
        )

    token = authorization[7:]  # 移除 "Bearer " 前綴
    return await verify_supabase_jwt(token)


def require_auth(user: Optional[dict] = Depends(get_current_user)) -> Optional[dict]:
    """
    要求認證的依賴注入

    - local 模式：直接通過（使用現有 session 機制）
    - supabase 模式：必須有有效的 JWT
    """
    if AUTH_MODE == "supabase" and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return user


def require_admin(user: Optional[dict] = Depends(get_current_user)) -> Optional[dict]:
    """
    要求管理員權限的依賴注入

    - local 模式：直接通過（假設已通過密碼驗證）
    - supabase 模式：檢查 JWT 中的 role
    """
    if AUTH_MODE == "local":
        return user

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    # 檢查 Supabase JWT 中的角色
    # Supabase 預設使用 app_metadata.role 或 user_metadata
    role = user.get("role") or user.get("app_metadata", {}).get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )

    return user


# ==========================================
# API Key 驗證（用於 OneStack → Aegis）
# ==========================================
AEGIS_API_KEY = os.getenv("AEGIS_API_KEY", "")


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> bool:
    """
    驗證 API Key（用於節點間通訊）
    """
    if not AEGIS_API_KEY:
        # 未設定 API Key 時，跳過驗證（開源用戶可能不需要）
        return True

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required"
        )

    # 使用 constant-time 比對防止 timing attack
    if not secrets.compare_digest(x_api_key, AEGIS_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    return True


def require_api_key(valid: bool = Depends(verify_api_key)) -> bool:
    """要求 API Key 的依賴注入"""
    return valid


# ==========================================
# Admin Token 驗證（用於管理端點）
# ==========================================

async def require_admin_token(request: Request):
    """驗證 admin token，localhost 放行（worker 內部呼叫）。
    非 localhost 請求必須帶有效 Bearer token 且 type == "admin"。
    """
    # localhost 放行（worker / 內部呼叫）
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return

    # 取得 Authorization header
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    token = auth_header[7:]
    payload = decode_session_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if payload.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
