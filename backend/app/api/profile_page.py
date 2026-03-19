"""
獨立的個人資料設定頁面 — 讓 Bot 使用者透過網頁設定敏感資料
不經過 chatmessage，避免密碼被記錄在對話表中。

欄位定義存在 SystemSetting("profile_fields")，格式：
[
  {"key": "ad_user", "title": "NAS / AD 帳號", "type": "text", "description": "..."},
  {"key": "ad_pass", "title": "NAS / AD 密碼", "type": "password", "description": "..."},
]
"""
import json
import time
import hmac
import hashlib
import base64
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.auth import _get_signing_secret

router = APIRouter()

# ==========================================
# 預設欄位定義（SystemSetting 沒有設時的 fallback）
# ==========================================
DEFAULT_PROFILE_FIELDS = [
    {
        "key": "ad_user",
        "title": "NAS / AD 帳號",
        "type": "text",
        "description": "公司 Active Directory 帳號，格式 DOMAIN\\username",
        "placeholder": "例如：GS-AD\\john.doe",
    },
    {
        "key": "ad_pass",
        "title": "NAS / AD 密碼",
        "type": "password",
        "description": "密碼不會顯示在聊天記錄中",
        "placeholder": "",
    },
]


def get_profile_fields() -> list:
    """從 SystemSetting 取得 profile 欄位定義"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting

        with Session(engine) as session:
            setting = session.get(SystemSetting, "profile_fields")
            if setting and setting.value:
                fields = json.loads(setting.value)
                if isinstance(fields, list) and fields:
                    return fields
    except Exception:
        pass
    return DEFAULT_PROFILE_FIELDS


# ==========================================
# Profile Token（帶 bot_user_id 的短效 token）
# ==========================================

def generate_profile_token(bot_user_id: int, ttl_minutes: int = 30) -> str:
    """產生帶 bot_user_id 的 profile token（預設 30 分鐘過期）"""
    payload = json.dumps({"uid": bot_user_id, "exp": int(time.time()) + ttl_minutes * 60})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_signing_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_profile_token(token: str) -> Optional[int]:
    """驗證 profile token，回傳 bot_user_id 或 None"""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(_get_signing_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("uid")
    except Exception:
        return None


def get_profile_url(bot_user_id: int, domain: str) -> str:
    """產生 profile 頁面的完整 URL"""
    token = generate_profile_token(bot_user_id)
    scheme = "http" if domain in ("localhost", "127.0.0.1") else "https"
    return f"{scheme}://{domain}/u/profile?token={token}"


def resolve_domain_for_user(bot_user_id: int) -> str:
    """從 BotUser 反查對應的 Domain hostname"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import BotUserProject, RoomProject, Domain

    with Session(engine) as session:
        bup = session.exec(
            select(BotUserProject).where(BotUserProject.bot_user_id == bot_user_id)
        ).first()

        if bup:
            rp = session.exec(
                select(RoomProject).where(RoomProject.project_id == bup.project_id)
            ).first()

            if rp:
                domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
                for d in domains:
                    try:
                        room_ids = json.loads(d.room_ids_json) if d.room_ids_json else []
                        if rp.room_id in room_ids:
                            return d.hostname
                    except (json.JSONDecodeError, TypeError):
                        continue

        default_domain = session.exec(
            select(Domain).where(Domain.is_default == True, Domain.is_active == True)
        ).first()
        if default_domain:
            return default_domain.hostname

    return "localhost:8899"


# ==========================================
# HTML 頁面（動態欄位）
# ==========================================

PROFILE_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>個人資料設定 — Aegis</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 32px; max-width: 480px; width: 100%; box-shadow: 0 25px 50px rgba(0,0,0,0.5); }
h1 { font-size: 20px; margin-bottom: 4px; color: #f8fafc; }
.subtitle { font-size: 13px; color: #94a3b8; margin-bottom: 24px; }
.user-info { background: #0f172a; border-radius: 8px; padding: 12px; margin-bottom: 24px; font-size: 13px; color: #94a3b8; }
.user-info strong { color: #e2e8f0; }
.field-group { margin-bottom: 16px; }
.field-group label { display: block; font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 6px; }
.field-group input { width: 100%; padding: 10px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 14px; outline: none; transition: border-color 0.2s; }
.field-group input:focus { border-color: #10b981; }
.field-group input::placeholder { color: #475569; }
.field-group .desc { font-size: 11px; color: #64748b; margin-top: 4px; }
.divider { border-top: 1px solid #334155; margin: 20px 0; }
.extra-section label { font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 8px; display: block; }
.field-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.field-row input { flex: 1; padding: 8px 10px; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; font-size: 13px; outline: none; }
.field-row input:focus { border-color: #10b981; }
.field-row .key-input { max-width: 120px; }
.remove-btn { background: #334155; color: #94a3b8; border: none; border-radius: 6px; padding: 8px 12px; cursor: pointer; font-size: 14px; flex-shrink: 0; }
.remove-btn:hover { background: #ef4444; color: white; }
.add-btn { background: none; border: 1px dashed #334155; color: #64748b; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 12px; width: auto; margin-top: 4px; }
.add-btn:hover { border-color: #10b981; color: #10b981; }
button[type=submit] { width: 100%; margin-top: 24px; padding: 12px; background: #10b981; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
button[type=submit]:hover { background: #059669; }
button[type=submit]:disabled { background: #334155; cursor: not-allowed; }
.msg { margin-top: 16px; padding: 12px; border-radius: 8px; font-size: 13px; display: none; }
.msg.success { display: block; background: #064e3b; border: 1px solid #10b981; color: #6ee7b7; }
.msg.error { display: block; background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; }
</style>
</head>
<body>
<div class="card">
  <h1>🛡️ 個人資料設定</h1>
  <p class="subtitle">設定後即可透過 AI 存取 NAS 等外部系統</p>

  <div class="user-info" id="userInfo">載入中...</div>

  <form id="profileForm">
    <div id="definedFields"></div>

    <div class="divider"></div>
    <div class="extra-section">
      <label>自訂欄位</label>
      <div id="extraFields"></div>
      <button type="button" class="add-btn" onclick="addExtraField()">+ 新增欄位</button>
    </div>

    <button type="submit" id="saveBtn">儲存</button>
  </form>
  <div class="msg" id="msg"></div>
</div>

<script>
const token = new URLSearchParams(location.search).get('token');
if (!token) {
  document.querySelector('.card').innerHTML = '<h1>❌ 無效的連結</h1><p class="subtitle">請在 Telegram 輸入 /profile 取得新連結</p>';
}

const API = '/api/v1/u/profile';
let fieldDefs = [];   // 欄位定義
let definedKeys = []; // 已定義的 key（不顯示在自訂欄位）

async function load() {
  try {
    const res = await fetch(API + '?token=' + token);
    if (!res.ok) {
      if (res.status === 401) {
        document.querySelector('.card').innerHTML = '<h1>⏰ 連結已過期</h1><p class="subtitle">請在 Telegram 重新輸入 /profile 取得新連結</p>';
        return;
      }
      throw new Error('載入失敗');
    }
    const data = await res.json();

    // 使用者資訊
    document.getElementById('userInfo').innerHTML =
      '<strong>' + esc(data.display_name || '使用者') + '</strong>' +
      ' — ' + esc(data.platform || '') +
      (data.username ? ' (@' + esc(data.username) + ')' : '');

    // 渲染定義欄位
    fieldDefs = data.fields || [];
    definedKeys = fieldDefs.map(f => f.key);
    const extra = data.extra || {};
    const container = document.getElementById('definedFields');

    fieldDefs.forEach(f => {
      const val = extra[f.key] || '';
      // 密碼欄位如果有值，顯示 placeholder 提示
      const placeholder = f.type === 'password' && val ? '（已設定，留空不變）' : (f.placeholder || '');
      container.innerHTML += `
        <div class="field-group">
          <label>${esc(f.title)}</label>
          <input type="${f.type || 'text'}" data-key="${esc(f.key)}"
                 value="${f.type === 'password' ? '' : esc(val)}"
                 placeholder="${esc(placeholder)}"
                 autocomplete="${f.type === 'password' ? 'current-password' : 'off'}">
          ${f.description ? '<p class="desc">' + esc(f.description) + '</p>' : ''}
        </div>`;
    });

    // 自訂欄位（不在 fieldDefs 中的 key）
    for (const [k, v] of Object.entries(extra)) {
      if (!definedKeys.includes(k)) {
        addExtraField(k, v);
      }
    }
  } catch (e) {
    showMsg('error', '載入失敗：' + e.message);
  }
}

function addExtraField(key, value) {
  const div = document.createElement('div');
  div.className = 'field-row';
  div.innerHTML =
    '<input class="key-input" placeholder="欄位名" value="' + esc(key || '') + '">' +
    '<input placeholder="值" value="' + esc(value || '') + '">' +
    '<button type="button" class="remove-btn" onclick="this.parentElement.remove()">✕</button>';
  document.getElementById('extraFields').appendChild(div);
}

document.getElementById('profileForm').onsubmit = async (e) => {
  e.preventDefault();
  const btn = document.getElementById('saveBtn');
  btn.disabled = true;
  btn.textContent = '儲存中...';

  try {
    const extra = {};

    // 定義欄位
    document.querySelectorAll('#definedFields input[data-key]').forEach(input => {
      const key = input.dataset.key;
      const val = input.value.trim();
      const fieldDef = fieldDefs.find(f => f.key === key);
      if (fieldDef && fieldDef.type === 'password' && !val) {
        // 密碼欄位留空 = 不修改（用 _keep 標記）
        extra[key] = '__KEEP__';
      } else if (val) {
        extra[key] = val;
      }
    });

    // 自訂欄位
    document.querySelectorAll('#extraFields .field-row').forEach(row => {
      const inputs = row.querySelectorAll('input');
      const k = inputs[0].value.trim();
      const v = inputs[1].value.trim();
      if (k) extra[k] = v;
    });

    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, extra })
    });

    if (!res.ok) throw new Error((await res.json()).detail || '儲存失敗');
    showMsg('success', '✅ 已儲存！可以關閉此頁面，回到 Telegram 繼續使用。');
  } catch (e) {
    showMsg('error', '❌ ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '儲存';
  }
};

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function showMsg(type, text) { const el = document.getElementById('msg'); el.className = 'msg ' + type; el.textContent = text; }
if (token) load();
</script>
</body>
</html>"""


# ==========================================
# API 路由
# ==========================================

class ProfileSaveRequest(BaseModel):
    token: str
    extra: dict


@router.get("/u/profile", response_class=HTMLResponse)
async def profile_page():
    """獨立的個人資料設定頁面"""
    return PROFILE_HTML


@router.get("/api/v1/u/profile")
async def get_profile(token: str):
    """取得使用者的 profile 資料 + 欄位定義"""
    bot_user_id = verify_profile_token(token)
    if not bot_user_id:
        raise HTTPException(status_code=401, detail="Token 無效或已過期")

    from sqlmodel import Session
    from app.database import engine
    from app.models.core import BotUser

    with Session(engine) as session:
        user = session.get(BotUser, bot_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="使用者不存在")

        extra = {}
        if user.extra_json:
            try:
                extra = json.loads(user.extra_json)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "display_name": user.username or user.platform_user_id,
            "platform": user.platform,
            "username": user.username,
            "extra": extra,
            "fields": get_profile_fields(),
        }


@router.post("/api/v1/u/profile")
async def save_profile(req: ProfileSaveRequest):
    """儲存使用者的 profile 資料"""
    bot_user_id = verify_profile_token(req.token)
    if not bot_user_id:
        raise HTTPException(status_code=401, detail="Token 無效或已過期")

    from sqlmodel import Session
    from app.database import engine
    from app.models.core import BotUser

    with Session(engine) as session:
        user = session.get(BotUser, bot_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="使用者不存在")

        # 讀取現有資料
        existing = {}
        if user.extra_json:
            try:
                existing = json.loads(user.extra_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # 合併：__KEEP__ 表示保留原值（密碼欄位留空時）
        new_extra = {}
        for k, v in req.extra.items():
            if v == "__KEEP__":
                if k in existing:
                    new_extra[k] = existing[k]
            else:
                new_extra[k] = v

        user.extra_json = json.dumps(new_extra, ensure_ascii=False)
        session.add(user)
        session.commit()

    return {"ok": True}
