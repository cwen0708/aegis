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
