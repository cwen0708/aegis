# Aegis 多帳號管理與 AI 團隊成員計畫

## 核心概念：三層架構

```
任務卡片 → AI 團隊成員（角色） → 帳號池（自動 failover）
         財務小陳               claude-max-A (主)
                                claude-pro-B (備)
         程式小溫               gemini-pro-1 (主)
                                gemini-pro-2 (備)
         架構師老張             gemini-pro-1 (主)
                                claude-max-A (備)
```

- **帳號 (Account)**：實體的 CLI 登入憑證（Claude OAuth / Gemini OAuth）
- **成員 (Member)**：虛擬角色，有名字、頭像、專長、綁定的帳號優先順序
- **任務路由**：從「階段 → provider」改為「階段 → 成員 → 最佳可用帳號」

---

## 1. 資料模型

### Account（帳號）

```python
class Account(SQLModel, table=True):
    id: int = Field(primary_key=True)
    provider: str          # "claude" | "gemini"
    name: str              # 顯示名稱，如 "Max 小良" / "Pro 備用"
    credential_file: str   # profile 檔案名，如 "claude-a.json"
    subscription: str      # "max" / "pro" / "ai-pro" 等
    email: str = ""        # 帳號 email（顯示用）
    is_healthy: bool = True  # token 是否有效
    created_at: datetime
```

### Member（AI 團隊成員）

```python
class Member(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str              # "財務小陳"
    avatar: str = ""       # emoji 或圖片 URL
    role: str = ""         # "資深開發者" / "架構師" / "測試員"
    description: str = ""  # 擅長什麼
    provider: str          # 主要 provider "claude" | "gemini"
    model: str = ""        # 指定 model，如 "opus" / "gemini-2.5-flash"
    is_enabled: bool = True
    created_at: datetime
```

### MemberAccount（成員-帳號綁定，有優先順序）

```python
class MemberAccount(SQLModel, table=True):
    id: int = Field(primary_key=True)
    member_id: int = Field(foreign_key="member.id")
    account_id: int = Field(foreign_key="account.id")
    priority: int = 0      # 0=主要, 1=備用1, 2=備用2...
```

### 修改 PHASE_ROUTING → PHASE_MEMBER

```python
# 舊：階段 → provider
PHASE_ROUTING = {
    "PLANNING": "gemini",
    "DEVELOPING": "claude",
}

# 新：階段 → member_id（在 Settings 頁面配置）
# 存在 SystemSetting key-value 中
# "phase_routing.PLANNING": "2"    (member_id=2, 程式小溫)
# "phase_routing.DEVELOPING": "1"  (member_id=1, 財務小陳)
```

---

## 2. 帳號儲存

### Claude 帳號池

```
~/.claude-profiles/
  ├── claude-max-a.json      # Account id=1
  ├── claude-pro-b.json      # Account id=2
  └── claude-max-c.json      # Account id=3
```

### Gemini 帳號池

```
~/.gemini-profiles/
  ├── gemini-pro-1.json      # Account id=4
  └── gemini-pro-2.json      # Account id=5
```

### 新增帳號流程

1. 使用者在 CLI 登入帳號（Claude `/logout` → 登入 / Gemini `/auth`）
2. 前端按「新增帳號」→ `POST /api/v1/accounts`
3. 後端讀取目前的 credential 檔案，複製到 profiles 目錄
4. 寫入 DB Account 表
5. 查詢一次用量確認 token 有效

---

## 3. 後端 API

### 帳號 CRUD

```
GET    /api/v1/accounts                 # 列出所有帳號 + 即時用量/配額
POST   /api/v1/accounts                 # 從目前 CLI 登入狀態新增帳號
DELETE /api/v1/accounts/:id             # 刪除帳號
```

### 成員 CRUD

```
GET    /api/v1/members                  # 列出所有成員 + 綁定帳號
POST   /api/v1/members                  # 新增成員
PUT    /api/v1/members/:id              # 更新成員資訊
DELETE /api/v1/members/:id              # 刪除成員
POST   /api/v1/members/:id/accounts     # 綁定帳號（含 priority）
DELETE /api/v1/members/:id/accounts/:account_id  # 解綁
```

### 帳號回傳格式

```json
[
  {
    "id": 1,
    "provider": "claude",
    "name": "Max 小良",
    "email": "cwen0708@...",
    "subscription": "max",
    "is_healthy": true,
    "usage": {
      "five_hour": { "utilization": 45.0, "resets_at": "..." },
      "seven_day": { "utilization": 72.0, "resets_at": "..." }
    }
  },
  {
    "id": 4,
    "provider": "gemini",
    "name": "Gemini 主號",
    "email": "cwen0708@gmail.com",
    "subscription": "ai-pro",
    "is_healthy": true,
    "quota": {
      "gemini-2.5-flash": { "remaining": 85.1 },
      "gemini-2.5-pro": { "remaining": 0 }
    }
  }
]
```

### 成員回傳格式

```json
[
  {
    "id": 1,
    "name": "財務小陳",
    "avatar": "👨‍💼",
    "role": "資深開發者",
    "provider": "claude",
    "model": "opus",
    "is_enabled": true,
    "accounts": [
      { "account_id": 1, "priority": 0, "name": "Max 小良", "usage_percent": 45 },
      { "account_id": 2, "priority": 1, "name": "Pro 備用", "usage_percent": 10 }
    ],
    "active_account": { "id": 1, "name": "Max 小良" }
  }
]
```

---

## 4. 自動帳號選擇（Runner）

```python
async def select_account_for_member(member_id: int) -> Account:
    """根據成員的帳號池，選擇最佳可用帳號"""
    bindings = get_member_accounts(member_id, ordered_by_priority=True)

    for binding in bindings:
        account = get_account(binding.account_id)
        if not account.is_healthy:
            continue

        if account.provider == "claude":
            usage = fetch_claude_usage(account)
            if usage and usage["five_hour"]["utilization"] < 80:
                activate_claude_account(account)
                return account

        elif account.provider == "gemini":
            quota = fetch_gemini_quota(account)
            target_model = get_member_model(member_id) or "gemini-2.5-flash"
            remaining = quota.get(target_model, {}).get("remaining", 0)
            if remaining > 10:
                activate_gemini_account(account)
                return account

    # 所有帳號都不可用
    raise NoAvailableAccountError(member_id)
```

### 切換流程

```
1. Poller 發現 pending 卡片
2. 根據 phase_routing 設定找到負責的 Member
3. select_account_for_member() 找最佳帳號
4. 覆蓋 ~/.claude/.credentials.json 或 ~/.gemini/oauth_creds.json
5. run_ai_task() 執行
6. 任務完成後不需要切回（下次任務會重新選）
```

---

## 5. 前端頁面

### 5.1 Agents 頁面（改版）

從「Claude / Gemini 兩區塊」改為「按成員分行」：

```
┌─────────────────────────────────────────────────────┐
│ AI 團隊狀態                                          │
├─────────────────────────────────────────────────────┤
│ 👨‍💼 財務小陳 · 資深開發者 · Claude Opus              │
│ ┌─────────────────────┐  ┌────────────────────────┐ │
│ │ Max 小良 (主) 45% ▓▓░│  │ C-58 · Greenshepherd  │ │
│ │ Pro 備用 (備) 10% ▓░░│  │ 修復 MQTT 連線問題     │ │
│ └─────────────────────┘  └────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ 👩‍💻 程式小溫 · 架構師 · Gemini 2.5 Flash             │
│ ┌─────────────────────┐  ┌────────────────────────┐ │
│ │ 主號 flash 14.9%  ▓░│  │ 等待任務分派...         │ │
│ │ 主號 pro   100%   ▓▓│  │                        │ │
│ └─────────────────────┘  └────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ 🧪 測試小李 · 驗證員 · Claude Sonnet                 │
│ ┌─────────────────────┐  ┌────────────────────────┐ │
│ │ Max 小良 (主) 45% ▓▓░│  │ 等待任務分派...         │ │
│ │（帳號可共用）         │  │                        │ │
│ └─────────────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

注意：同一個帳號可以被多個成員共用（如「Max 小良」同時被小陳和小李使用）。

### 5.2 新頁面：團隊管理（Team）

路由：`/team`

功能：
- **成員卡片列表**：新增 / 編輯 / 刪除 / 啟用停用
- **帳號管理區**：新增帳號（觸發 CLI 登入流程）、刪除、查看健康狀態
- **綁定設定**：拖曳排序帳號優先順序
- **階段路由設定**：哪個階段分給哪個成員

```
┌──────────────────────────────────────────────────┐
│ 團隊管理                                          │
├──────────────────────────────────────────────────┤
│                                                  │
│ [成員管理]  [帳號管理]  [路由設定]                   │
│                                                  │
│ ── 成員管理 ──────────────────────────────────── │
│                                                  │
│  + 新增成員                                       │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │ 👨‍💼 財務小陳                           │        │
│  │ 角色：資深開發者                        │        │
│  │ Provider：Claude  Model：opus         │        │
│  │ 帳號：                                 │        │
│  │   ① Max 小良 (主)    [↑] [↓] [✕]     │        │
│  │   ② Pro 備用 (備)    [↑] [↓] [✕]     │        │
│  │   [+ 綁定帳號]                         │        │
│  │                         [編輯] [刪除]  │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│ ── 帳號管理 ──────────────────────────────────── │
│                                                  │
│  + 新增 Claude 帳號   + 新增 Gemini 帳號          │
│                                                  │
│  Claude                                          │
│  ┌────────────────────────────┐                  │
│  │ Max 小良 · max · ✅ 健康    │                  │
│  │ Pro 備用 · pro · ✅ 健康    │                  │
│  └────────────────────────────┘                  │
│  Gemini                                          │
│  ┌────────────────────────────┐                  │
│  │ 主號 · ai-pro · ✅ 健康     │                  │
│  └────────────────────────────┘                  │
│                                                  │
│ ── 路由設定 ──────────────────────────────────── │
│                                                  │
│  Planning   → [程式小溫 ▼]                        │
│  Developing → [財務小陳 ▼]                        │
│  Verifying  → [測試小李 ▼]                        │
│  Reviewing  → [程式小溫 ▼]                        │
│  Scheduled  → [財務小陳 ▼]                        │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 6. 實作順序

| # | 內容 | 新增/修改檔案 |
|---|------|-------------|
| 1 | DB Model：Account, Member, MemberAccount | `models/core.py` |
| 2 | 帳號管理核心：profiles 讀寫、用量查詢 | `core/account_manager.py` |
| 3 | 帳號 + 成員 CRUD API | `api/routes.py` |
| 4 | Runner 整合：任務派發前自動選帳號 | `core/poller.py`, `core/runner.py` |
| 5 | 前端 Team 頁面 | `views/Team.vue`, `router/index.ts`, `App.vue` |
| 6 | 前端 Agents 頁面改版（按成員分行） | `views/Agents.vue` |
| 7 | 前端 Settings 路由設定區塊 | `views/Settings.vue` 或整合到 Team |

---

## 7. 注意事項

### 並行任務衝突
- Phase 1：同一時間只用一個帳號執行（semaphore 保護切換操作）
- Phase 2：用 `CLAUDE_CONFIG_DIR` 讓不同成員的任務同時使用不同帳號

### Token 有效期
- Claude OAuth token 約 1 小時過期，需要 refresh
- Gemini OAuth token 約 1 小時過期，已實作 refresh
- 每次查詢用量時順便檢查 token 健康狀態

### 帳號可共用
- 多個成員可以綁定同一個帳號（如 Claude Max 帳號同時被開發者和測試員使用）
- 用量是帳號級別的，不是成員級別的

### 新增帳號的 UX
- 前端顯示引導步驟：「請先在 CLI 登入新帳號，然後回來按確認」
- 後端檢查 credential 檔案是否存在且 token 有效
- 自動偵測 email 和訂閱類型
