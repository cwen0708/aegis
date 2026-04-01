"""auth.py 純函式單元測試（不需 DB）"""
import time
import pytest
from app.core.auth import (
    generate_session_token,
    verify_session_token,
    decode_session_token,
    hash_password,
    check_password,
    get_auth_mode,
)


@pytest.fixture(autouse=True)
def _fixed_secret(monkeypatch):
    """固定 HMAC 密鑰，避免依賴 DB"""
    import app.core.auth as auth_mod
    monkeypatch.setenv("AEGIS_SESSION_SECRET", "test-secret-key")
    # 重置快取，讓 _get_signing_secret 重新讀取 env
    auth_mod._signing_secret = None
    auth_mod._signing_secret_ts = 0


# ==========================================
# generate_session_token
# ==========================================

def test_generate_session_token_format():
    token = generate_session_token()
    parts = token.split(".")
    assert len(parts) == 2, "token 應為 {base64}.{hex} 格式"
    # sig 部分是 sha256 hex，64 字元
    assert len(parts[1]) == 64


# ==========================================
# verify_session_token
# ==========================================

def test_verify_session_token_valid():
    token = generate_session_token()
    assert verify_session_token(token) is True


def test_verify_session_token_invalid():
    assert verify_session_token("invalid-token") is False


# ==========================================
# decode_session_token
# ==========================================

def test_decode_session_token_payload():
    token = generate_session_token(user_type="admin", user_id=5)
    payload = decode_session_token(token)
    assert payload is not None
    assert "exp" in payload
    assert payload["type"] == "admin"
    assert payload["uid"] == 5


def test_decode_session_token_expired(monkeypatch):
    # 產生一個 TTL=1 小時的 token，然後把時間快轉
    token = generate_session_token(ttl_hours=1)
    monkeypatch.setattr(time, "time", lambda: time.time() + 7200)
    assert decode_session_token(token) is None


def test_decode_session_token_tampered_signature():
    token = generate_session_token()
    payload_b64, sig = token.split(".", 1)
    tampered = payload_b64 + "." + ("0" * 64)
    assert decode_session_token(tampered) is None


def test_decode_session_token_no_dot():
    assert decode_session_token("nodottoken") is None


def test_decode_session_token_old_format_no_type():
    """舊格式 token（無 type 欄位）應回傳 None"""
    import json, base64, hmac, hashlib
    from app.core.auth import _get_signing_secret

    payload = json.dumps({"exp": int(time.time()) + 3600, "uid": 0})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_signing_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    token = f"{payload_b64}.{sig}"
    assert decode_session_token(token) is None


# ==========================================
# hash_password / check_password
# ==========================================

def test_hash_password_prefix():
    hashed = hash_password("mypassword")
    assert hashed.startswith("$scrypt$")


def test_check_password_correct():
    hashed = hash_password("mypassword")
    assert check_password("mypassword", hashed) is True


def test_check_password_wrong():
    hashed = hash_password("mypassword")
    assert check_password("wrongpassword", hashed) is False


def test_check_password_plaintext_compat():
    """明文向後相容"""
    assert check_password("plaintext123", "plaintext123") is True
    assert check_password("wrong", "plaintext123") is False


# ==========================================
# get_auth_mode
# ==========================================

def test_get_auth_mode_default():
    assert get_auth_mode() == "local"


# ==========================================
# verify_local_password
# ==========================================

def test_verify_local_password_reads_from_db(monkeypatch):
    """從 SystemSetting 讀取密碼並驗證正確密碼"""
    from unittest.mock import MagicMock
    from app.models.core import SystemSetting
    from app.core.auth import hash_password, verify_local_password

    hashed = hash_password("custom_pass")
    setting = SystemSetting(key="admin_password", value=hashed)

    mock_session = MagicMock()
    mock_session.get.return_value = setting

    assert verify_local_password("custom_pass", mock_session) is True
    assert verify_local_password("wrong_pass", mock_session) is False


def test_verify_local_password_fallback_to_default(monkeypatch):
    """DB 無密碼時（session.get 回傳 None）使用 DEFAULT_PASSWORD"""
    from unittest.mock import MagicMock
    import app.core.auth as auth_mod
    from app.core.auth import verify_local_password

    monkeypatch.setattr(auth_mod, "DEFAULT_PASSWORD", "aegis2026!")

    mock_session = MagicMock()
    mock_session.get.return_value = None  # 模擬 DB 無此設定

    assert verify_local_password("aegis2026!", mock_session) is True
    assert verify_local_password("wrong", mock_session) is False


def test_verify_local_password_correct_and_wrong(monkeypatch):
    """直接測試正確/錯誤密碼回傳值"""
    from unittest.mock import MagicMock
    from app.models.core import SystemSetting
    from app.core.auth import hash_password, verify_local_password

    stored = hash_password("secret123")
    setting = SystemSetting(key="admin_password", value=stored)

    mock_session = MagicMock()
    mock_session.get.return_value = setting

    assert verify_local_password("secret123", mock_session) is True
    assert verify_local_password("notSecret", mock_session) is False


# ==========================================
# verify_api_key
# ==========================================

async def test_verify_api_key_valid(monkeypatch):
    """AEGIS_API_KEY 已設定，傳入正確 key → True"""
    import app.core.auth as auth_mod
    from app.core.auth import verify_api_key

    monkeypatch.setattr(auth_mod, "AEGIS_API_KEY", "my-secret-key")
    result = await verify_api_key(x_api_key="my-secret-key")
    assert result is True


async def test_verify_api_key_invalid(monkeypatch):
    """AEGIS_API_KEY 已設定，傳入錯誤 key → HTTPException 401"""
    import app.core.auth as auth_mod
    from app.core.auth import verify_api_key
    from fastapi import HTTPException

    monkeypatch.setattr(auth_mod, "AEGIS_API_KEY", "my-secret-key")
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(x_api_key="wrong-key")
    assert exc_info.value.status_code == 401


async def test_verify_api_key_not_set(monkeypatch):
    """未設定 AEGIS_API_KEY 時跳過驗證，直接回傳 True"""
    import app.core.auth as auth_mod
    from app.core.auth import verify_api_key

    monkeypatch.setattr(auth_mod, "AEGIS_API_KEY", "")
    result = await verify_api_key(x_api_key=None)
    assert result is True


def test_require_api_key_wraps_verify(monkeypatch):
    """require_api_key 依賴注入：直接傳入 valid=True 應回傳 True"""
    from app.core.auth import require_api_key

    assert require_api_key(valid=True) is True


# ==========================================
# require_admin_token
# ==========================================

def _make_request(host: str, authorization: str = "") -> "Request":
    """建立 mock Request"""
    from unittest.mock import MagicMock
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = host
    req.headers = {"authorization": authorization} if authorization else {}
    return req


async def test_require_admin_token_localhost():
    """localhost 請求直接放行，不需 token"""
    from app.core.auth import require_admin_token

    req = _make_request("127.0.0.1")
    # 不應 raise
    await require_admin_token(req)


async def test_require_admin_token_localhost_ipv6():
    """::1 (IPv6 localhost) 也放行"""
    from app.core.auth import require_admin_token

    req = _make_request("::1")
    await require_admin_token(req)


async def test_require_admin_token_valid_remote():
    """遠端請求帶有效 admin token → 放行"""
    from app.core.auth import require_admin_token, generate_session_token

    token = generate_session_token(user_type="admin")
    req = _make_request("10.0.0.1", authorization=f"Bearer {token}")
    await require_admin_token(req)


async def test_require_admin_token_invalid_token():
    """遠端請求帶無效 token → HTTPException 401"""
    from app.core.auth import require_admin_token
    from fastapi import HTTPException

    req = _make_request("10.0.0.1", authorization="Bearer invalid.token")
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(req)
    assert exc_info.value.status_code == 401


async def test_require_admin_token_non_admin_type():
    """遠端請求帶 user type token → HTTPException 403"""
    from app.core.auth import require_admin_token, generate_session_token
    from fastapi import HTTPException

    token = generate_session_token(user_type="user", user_id=42)
    req = _make_request("10.0.0.1", authorization=f"Bearer {token}")
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(req)
    assert exc_info.value.status_code == 403


async def test_require_admin_token_no_bearer_prefix():
    """Authorization header 無 Bearer 前綴 → HTTPException 401"""
    from app.core.auth import require_admin_token, generate_session_token
    from fastapi import HTTPException

    token = generate_session_token(user_type="admin")
    req = _make_request("10.0.0.1", authorization=token)  # 缺少 "Bearer "
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_token(req)
    assert exc_info.value.status_code == 401
