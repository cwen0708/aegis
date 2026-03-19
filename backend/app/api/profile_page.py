"""
獨立的個人資料設定頁面 — 讓 Bot 使用者透過網頁設定 AD 帳密等敏感資料
不經過 chatmessage，避免密碼被記錄在對話表中。

流程：
1. 使用者在 Telegram 輸入 /profile
2. Bot 回覆一個帶 token 的連結：https://{domain}/u/profile?token=xxx
3. 使用者開啟網頁，看到表單，填寫 AD 帳密
4. 直接寫入 BotUser.extra_json
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
    """從 BotUser 反查對應的 Domain hostname

    查詢鏈路：BotUser → BotUserProject → Project → RoomProject → Room → Domain
    找不到就用預設 Domain 或 fallback localhost
    """
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import BotUserProject, RoomProject, Domain

    with Session(engine) as session:
        # 1. 找使用者綁定的專案
        bup = session.exec(
            select(BotUserProject).where(BotUserProject.bot_user_id == bot_user_id)
        ).first()

        if bup:
            # 2. 找專案所屬的 Room
            rp = session.exec(
                select(RoomProject).where(RoomProject.project_id == bup.project_id)
            ).first()

            if rp:
                # 3. 找 Room 對應的 Domain
                domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
                for d in domains:
                    try:
                        room_ids = json.loads(d.room_ids_json) if d.room_ids_json else []
                        if rp.room_id in room_ids:
                            return d.hostname
                    except (json.JSONDecodeError, TypeError):
                        continue

        # Fallback: 預設 Domain
        default_domain = session.exec(
            select(Domain).where(Domain.is_default == True, Domain.is_active == True)
        ).first()
        if default_domain:
            return default_domain.hostname

    return "localhost:8899"


# ==========================================
# HTML 頁面
# ==========================================

PROFILE_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>個人資料設定 — Aegis</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 32px; max-width: 420px; width: 100%; margin: 16px; box-shadow: 0 25px 50px rgba(0,0,0,0.5); }
h1 { font-size: 20px; margin-bottom: 4px; color: #f8fafc; }
.subtitle { font-size: 13px; color: #94a3b8; margin-bottom: 24px; }
.user-info { background: #0f172a; border-radius: 8px; padding: 12px; margin-bottom: 24px; font-size: 13px; color: #94a3b8; }
.user-info strong { color: #e2e8f0; }
label { display: block; font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 6px; margin-top: 16px; }
input { width: 100%; padding: 10px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 14px; outline: none; transition: border-color 0.2s; }
input:focus { border-color: #10b981; }
input::placeholder { color: #475569; }
.help { font-size: 11px; color: #64748b; margin-top: 4px; }
button { width: 100%; margin-top: 24px; padding: 12px; background: #10b981; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
button:hover { background: #059669; }
button:disabled { background: #334155; cursor: not-allowed; }
.msg { margin-top: 16px; padding: 12px; border-radius: 8px; font-size: 13px; display: none; }
.msg.success { display: block; background: #064e3b; border: 1px solid #10b981; color: #6ee7b7; }
.msg.error { display: block; background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; }
.fields { margin-top: 8px; }
.field-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.field-row input { flex: 1; }
.field-row .key-input { max-width: 120px; }
.remove-btn { background: #334155; color: #94a3b8; border: none; border-radius: 6px; padding: 8px 12px; cursor: pointer; font-size: 14px; }
.remove-btn:hover { background: #ef4444; color: white; }
.add-btn { margin-top: 8px; background: none; border: 1px dashed #334155; color: #64748b; padding: 8px; border-radius: 8px; cursor: pointer; font-size: 12px; width: auto; }
.add-btn:hover { border-color: #10b981; color: #10b981; }
.divider { border-top: 1px solid #334155; margin: 20px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>🛡️ 個人資料設定</h1>
  <p class="subtitle">設定後即可透過 AI 存取 NAS 檔案等外部系統</p>

  <div class="user-info" id="userInfo">載入中...</div>

  <form id="profileForm">
    <label>NAS / AD 帳號</label>
    <input type="text" id="adUser" placeholder="例如：GS-AD\\john.doe" autocomplete="username">
    <p class="help">公司 Active Directory 帳號，格式 DOMAIN\\username</p>

    <label>NAS / AD 密碼</label>
    <input type="password" id="adPass" placeholder="••••••••" autocomplete="current-password">
    <p class="help">密碼不會顯示在聊天記錄中</p>

    <div class="divider"></div>
    <label>其他欄位</label>
    <div class="fields" id="extraFields"></div>
    <button type="button" class="add-btn" onclick="addField()">+ 新增欄位</button>

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

    // 顯示使用者資訊
    document.getElementById('userInfo').innerHTML =
      '<strong>' + (data.display_name || '使用者') + '</strong>' +
      ' — ' + (data.platform || '') +
      (data.username ? ' (@' + data.username + ')' : '');

    // 填入現有資料
    const extra = data.extra || {};
    document.getElementById('adUser').value = extra.ad_user || '';
    document.getElementById('adPass').value = extra.ad_pass || '';

    // 其他欄位
    for (const [k, v] of Object.entries(extra)) {
      if (k !== 'ad_user' && k !== 'ad_pass') {
        addField(k, v);
      }
    }
  } catch (e) {
    showMsg('error', '載入失敗：' + e.message);
  }
}

function addField(key, value) {
  const div = document.createElement('div');
  div.className = 'field-row';
  div.innerHTML = '<input class="key-input" placeholder="key" value="' + (key || '') + '">' +
    '<input placeholder="value" value="' + (value || '') + '">' +
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
    const adUser = document.getElementById('adUser').value.trim();
    const adPass = document.getElementById('adPass').value.trim();
    if (adUser) extra.ad_user = adUser;
    if (adPass) extra.ad_pass = adPass;

    // 其他欄位
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

function showMsg(type, text) {
  const el = document.getElementById('msg');
  el.className = 'msg ' + type;
  el.textContent = text;
}

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
    """取得使用者的 profile 資料"""
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
        }


@router.post("/api/v1/u/profile")
async def save_profile(req: ProfileSaveRequest):
    """儲存使用者的 profile 資料（直接寫入 extra_json，不經過 chatmessage）"""
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

        user.extra_json = json.dumps(req.extra, ensure_ascii=False)
        session.add(user)
        session.commit()

    return {"ok": True}
