# Aegis P2 Bot 用戶與權限系統

> 狀態：規劃完成（已審查）
> 建立日期：2026-03-09
> 前置：P1 多頻道架構（已完成）

---

## 一、目標

讓 Aegis Bot 支援多人使用，具備：
1. **用戶驗證**：邀請碼加入、身份識別
2. **權限分級**：不同角色有不同操作權限
3. **Member 綁定**：每個用戶對應一個 AI 角色（人設 + 配額）
4. **自然語言對話**：非命令訊息由 AI 處理

---

## 二、使用場景

### 場景 A：老闆（查進度、下指令）
```
老闆：「OneStack 進度如何？」
Bot：「📊 OneStack 進度
      ✅ 完成：12 張卡片
      🔵 進行中：3 張
      🟡 待處理：5 張」

老闆：「#235 什麼時候完成？」
Bot：「開發中，預計今天下班前」

老闆：「催一下」
Bot：「✅ 已通知開發者加速處理」
```

### 場景 B：客戶（查詢、反饋）
```
客戶：/verify CUSTA2024
Bot：「✅ 驗證成功！我是小美，負責協助您」

客戶：「網站什麼時候上線？」
Bot：「📅 預計 3/15，目前進度 80%」

客戶：「能加個收藏功能嗎？」
Bot：「📝 已記錄需求 #250，會有人回覆您」
```

### 場景 C：開發者（執行任務）
```
開發者：「我接下來做什麼？」
Bot：「📋 你的任務：#245 修復登入 bug（高優先）」

開發者：/run 245
Bot：「🚀 開始執行，完成後通知你」
```

---

## 三、權限等級

| Level | 名稱 | 說明 | 可用功能 |
|-------|------|------|----------|
| 0 | 未驗證 | 陌生人 | /help, /start, /verify |
| 1 | 訪客 | 已驗證的外部人員 | 對話、查看限定專案 |
| 2 | 成員 | 內部人員 | 執行任務、建立卡片 |
| 3 | 管理員 | 你 | 完整權限、管理用戶 |

### 命令權限矩陣

| 命令 | L0 | L1 | L2 | L3 | 說明 |
|------|----|----|----|----|------|
| /help | ✅ | ✅ | ✅ | ✅ | 顯示可用命令 |
| /start | ✅ | ✅ | ✅ | ✅ | 歡迎訊息 |
| /verify `<code>` | ✅ | - | - | - | 驗證邀請碼 |
| /me | ❌ | ✅ | ✅ | ✅ | 查看自己資訊 |
| /status | ❌ | ✅ | ✅ | ✅ | 系統狀態 |
| /card list | ❌ | ✅ | ✅ | ✅ | 列出卡片 |
| /card `<id>` | ❌ | ✅ | ✅ | ✅ | 查看卡片詳情 |
| /bind | ❌ | ✅ | ✅ | ✅ | 綁定通知（P1） |
| /unbind | ❌ | ✅ | ✅ | ✅ | 解除綁定（P1） |
| 自然語言對話 | ❌ | ✅ | ✅ | ✅ | AI 對話 |
| /run `<id>` | ❌ | ❌ | ✅ | ✅ | 執行任務 |
| /stop `<id>` | ❌ | ❌ | ✅ | ✅ | 停止任務 |
| /card create | ❌ | ❌ | ✅ | ✅ | 建立卡片 |
| /switch `<member>` | ❌ | ❌ | ✅ | ✅ | 切換 AI 角色 |
| /user list | ❌ | ❌ | ❌ | ✅ | 列出用戶 |
| /user info `<id>` | ❌ | ❌ | ❌ | ✅ | 用戶詳情 |
| /user grant | ❌ | ❌ | ❌ | ✅ | 設定權限 |
| /user ban | ❌ | ❌ | ❌ | ✅ | 停用用戶 |
| /user assign | ❌ | ❌ | ❌ | ✅ | 指派 Member |
| /invite | ❌ | ❌ | ❌ | ✅ | 產生邀請碼 |

> **L0**：未驗證 / **L1**：訪客 / **L2**：成員 / **L3**：管理員

---

## 四、資料模型

### 4.1 BotUser（新增）

```python
class BotUser(SQLModel, table=True):
    """Bot 用戶（真人）"""
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_botuser_platform_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # 平台身份
    platform: str = Field(index=True)       # telegram, line...
    platform_user_id: str = Field(index=True)
    username: Optional[str] = None          # 顯示名稱

    # 權限
    level: int = Field(default=0)           # 0-3
    is_active: bool = Field(default=True)

    # 綁定（預設 Member，用於對話）
    default_member_id: Optional[int] = Field(default=None, foreign_key="member.id")

    # 時間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: Optional[datetime] = None

    # 安全性
    failed_verify_count: int = Field(default=0)      # 驗證失敗次數
    last_failed_at: Optional[datetime] = None        # 最後失敗時間
    locked_until: Optional[datetime] = None          # 鎖定到期時間
```

### 4.2 BotUserProject（新增）

```python
class BotUserProject(SQLModel, table=True):
    """用戶與專案的多對多關聯（權限控制）"""
    __tablename__ = "bot_user_project"
    __table_args__ = (
        UniqueConstraint("bot_user_id", "project_id", name="uq_botuserproject"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)

    # === 身份描述（給 AI 讀的自然語言） ===
    display_name: str = Field(default="")         # "王小華"
    description: str = Field(default="")          # "案場業主，可查看發電資料，不可修改設定"

    # === 硬性權限（程式碼強制檢查，防止 AI 誤判） ===
    can_view: bool = Field(default=True)          # 可查看卡片
    can_create_card: bool = Field(default=False)  # 可建立卡片
    can_run_task: bool = Field(default=False)     # 可執行任務
    can_comment: bool = Field(default=True)       # 可留言
    can_access_sensitive: bool = Field(default=False)  # 可存取敏感資料

    # 預設專案（建卡時優先使用）
    is_default: bool = Field(default=False)

    # 元資料
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[int] = Field(default=None)  # 誰授權的（BotUser ID）
```

> **設計說明**：
> 1. **雙層權限控制**：`description` 給 AI 理解用戶身份，`can_*` 欄位由程式碼強制檢查
> 2. AI 依據 description 判斷回答範圍和語氣，但實際操作仍由硬性權限把關
> 3. 例如 description 寫「可查看發電資料」，AI 會主動提供相關資訊；但若 `can_run_task=False`，即使 AI 想幫忙執行也會被程式碼擋下

#### 權限設計對照

| 欄位 | 類型 | 用途 |
|------|------|------|
| `display_name` | 描述層 | AI 稱呼用戶（「王先生您好」） |
| `description` | 描述層 | AI 理解用戶身份與權限範圍 |
| `can_view` | 硬性權限 | 程式碼檢查：能否查看卡片 |
| `can_create_card` | 硬性權限 | 程式碼檢查：能否建立卡片 |
| `can_run_task` | 硬性權限 | 程式碼檢查：能否執行 AI 任務 |
| `can_access_sensitive` | 硬性權限 | 程式碼檢查：能否存取敏感資料（如成本、利潤） |

#### Description 範例

| 場景 | display_name | description |
|------|--------------|-------------|
| 案場業主 | 王小華 | 「台南案場業主，可查看發電資料和維運進度，不可修改設定或查看財務報表」 |
| 維運工程師 | 李大明 | 「維運組長，負責北區三座案場，可查看設備狀態、建立維修工單、執行診斷任務」 |
| 財務人員 | 陳會計 | 「財務部門，可查看所有專案的成本和收入報表，不可建立或修改工單」 |
| 外部稽核 | 張稽核 | 「年度稽核人員，僅可查看 2025 年度結案專案，限期至 2026/03/31」 |

#### UI 權限模板（不存資料庫）

管理員新增用戶時，UI 提供快捷模板自動填入 description 和 can_* 欄位：

| 模板 | description 預設值 | can_view | can_create | can_run | can_sensitive |
|------|-------------------|----------|------------|---------|---------------|
| 訪客 | 「外部人員，僅可查看專案進度」 | ✅ | ❌ | ❌ | ❌ |
| 成員 | 「內部成員，可查看、建立卡片和執行任務」 | ✅ | ✅ | ✅ | ❌ |
| 管理員 | 「專案管理員，擁有完整權限」 | ✅ | ✅ | ✅ | ✅ |

> **設計說明**：模板只是 UI 快捷鍵，不存到資料庫。選擇模板後自動填入預設值，
> 管理員可再修改 description 和權限勾選。這樣保持資料模型乾淨，同時操作方便。

### 4.3 BotUserMember（新增）

```python
class BotUserMember(SQLModel, table=True):
    """用戶與 Member 的多對多關聯"""
    __table_args__ = (
        UniqueConstraint("bot_user_id", "member_id", name="uq_botusermember"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)

    # 關聯屬性
    is_default: bool = Field(default=False)     # 是否為預設 Member
    can_switch: bool = Field(default=True)      # 是否可切換到此 Member
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

> **設計說明**：一個 BotUser 可關聯多個 Member（如員工同時負責客服和技術支援），
> `is_default` 標記預設角色，`/switch` 命令可在允許的 Member 間切換。

### 4.4 InviteCode（新增）

```python
class InviteCode(SQLModel, table=True):
    """邀請碼"""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "CUSTA2024"

    # 配置
    target_level: int = Field(default=1)
    target_member_id: Optional[int] = None

    # 專案授權
    allowed_projects: Optional[str] = None      # JSON: [1, 2, 3]

    # 用戶身份描述（驗證時自動填入 BotUserProject）
    user_display_name: str = Field(default="")  # "王小華"
    user_description: str = Field(default="")   # "案場業主，可查看發電資料..."

    # 預設權限（驗證時自動填入 BotUserProject）
    default_can_view: bool = Field(default=True)
    default_can_create_card: bool = Field(default=False)
    default_can_run_task: bool = Field(default=False)
    default_can_access_sensitive: bool = Field(default=False)

    # 使用限制
    max_uses: int = Field(default=1)
    used_count: int = Field(default=0)
    expires_at: Optional[datetime] = None

    # 元資料
    created_by: int         # 建立者 BotUser ID
    created_at: datetime
    note: str = ""          # "給客戶A用"
```

> **驗證成功時自動建立 BotUserProject**：邀請碼的 `allowed_projects` 會自動轉為
> BotUserProject 記錄，第一個專案設為 `is_default=True`。

#### 邀請流程

1. 管理員執行 `/invite` 時填入用戶姓名、描述和預設權限
2. 邀請碼產生後傳給客戶
3. 客戶執行 `/verify <code>` 驗證
4. 系統自動建立 BotUserProject，帶入 `display_name`、`description` 和 `can_*` 權限
5. AI 後續對話時能用正確的稱呼和權限範圍回應

---

## 五、架構流程

### 5.1 訊息處理流程

```
InboundMessage
      │
      ▼
┌─────────────────────────────────────┐
│ 1. 查詢 BotUser                     │
│    SELECT * FROM botuser            │
│    WHERE platform=? AND user_id=?   │
└──────────────────┬──────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
    未找到                  找到
        │                     │
        ▼                     ▼
   自動建立              更新 last_active
   level=0                    │
        │                     │
        └──────────┬──────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 2. 解析命令/訊息                    │
└──────────────────┬──────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
    是命令              自然語言
        │                     │
        ▼                     ▼
┌───────────────┐    ┌───────────────┐
│ 3. 權限檢查   │    │ 3. 檢查 level │
│ cmd → level   │    │ level >= 1?   │
└───────┬───────┘    └───────┬───────┘
        │                     │
        ▼                     ▼
┌───────────────┐    ┌───────────────┐
│ 4. 執行命令   │    │ 4. AI 對話    │
│ handlers.py   │    │ → Member      │
└───────────────┘    │ → Account     │
                     │ → CLI         │
                     └───────────────┘
```

### 5.2 驗證流程

```
用戶 /verify ABC123
         │
         ▼
┌─────────────────────────────────────┐
│ 查詢 InviteCode WHERE code=ABC123  │
└──────────────────┬──────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
    無效/過期              有效
        │                     │
        ▼                     ▼
    回傳錯誤         更新 BotUser:
                     - level = code.target_level
                     - member_id = code.target_member_id
                           │
                           ▼
                     建立 BotUserPermission
                     (依 allowed_projects)
                           │
                           ▼
                     code.used_count += 1
                           │
                           ▼
                     回傳成功訊息
```

---

## 六、新增命令

### 6.1 用戶命令

| 命令 | 說明 | 權限 |
|------|------|------|
| /verify <code> | 驗證邀請碼 | L0 |
| /me | 查看自己的資訊 | L1+ |
| /switch <member> | 切換 AI 角色 | L2+ |

### 6.2 管理員命令

| 命令 | 說明 |
|------|------|
| /invite [level] [note] | 產生邀請碼 |
| /user list | 列出所有用戶 |
| /user info <id> | 查看用戶詳情 |
| /user grant <id> <level> | 設定用戶等級 |
| /user assign <id> <member_id> | 指派 Member |
| /user ban <id> | 停用用戶 |

---

## 七、AI 對話整合

### 7.1 對話模型（正規化）

```python
class ChatSession(SQLModel, table=True):
    """對話 Session（User × Member × Channel）"""
    __table_args__ = (
        UniqueConstraint("bot_user_id", "member_id", "chat_id", name="uq_chatsession"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    chat_id: str = Field(index=True)        # 對話頻道 ID

    # Token 統計（用於限流）
    total_input_tokens: int = Field(default=0)
    total_output_tokens: int = Field(default=0)
    message_count: int = Field(default=0)

    # 時間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_at: Optional[datetime] = None


class ChatMessage(SQLModel, table=True):
    """對話訊息（獨立儲存，支援高效查詢）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)

    role: str               # "user" | "assistant"
    content: str            # 訊息內容
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

> **設計說明**：將原本的 JSON 陣列拆成獨立 ChatMessage 表，
> 優點：可高效查詢歷史、精確統計 token、支援分頁、便於清理舊訊息。

### 7.2 成員 Profile 整合

每個 Member 在檔案系統有獨立的 profile 目錄：

```
.aegis/members/{slug}/
├── soul.md              ← 人設靈魂檔案（必載入）
├── skills/              ← 技能目錄
└── memory/
    ├── short-term/      ← 短期記憶
    └── long-term/       ← 長期記憶
```

已有工具函式（`app/core/member_profile.py`）：
- `get_soul_content(slug)` → 讀取 soul.md
- `get_member_memory_dir(slug)` → 取得記憶目錄

### 7.3 專案存取查詢

```python
def get_user_projects(bot_user_id: int, can_view_only: bool = True) -> list[Project]:
    """取得用戶可存取的專案"""
    with Session(engine) as session:
        stmt = (
            select(Project)
            .join(BotUserProject, BotUserProject.project_id == Project.id)
            .where(BotUserProject.bot_user_id == bot_user_id)
        )
        if can_view_only:
            stmt = stmt.where(BotUserProject.can_view == True)
        return session.exec(stmt).all()


def get_default_project(bot_user_id: int) -> Optional[Project]:
    """取得用戶的預設專案"""
    with Session(engine) as session:
        stmt = (
            select(Project)
            .join(BotUserProject, BotUserProject.project_id == Project.id)
            .where(
                BotUserProject.bot_user_id == bot_user_id,
                BotUserProject.is_default == True,
            )
        )
        return session.exec(stmt).first()


def can_user_create_card(bot_user_id: int, project_id: int) -> bool:
    """檢查用戶能否在指定專案建卡"""
    with Session(engine) as session:
        stmt = select(BotUserProject).where(
            BotUserProject.bot_user_id == bot_user_id,
            BotUserProject.project_id == project_id,
            BotUserProject.can_create_card == True,
        )
        return session.exec(stmt).first() is not None
```

### 7.4 對話處理

```python
async def handle_chat(msg: InboundMessage, bot_user: BotUser):
    """處理自然語言對話"""
    from app.core.member_profile import get_soul_content

    # 0. 檢查限流
    if await is_rate_limited(bot_user.id):
        return "⏳ 請求過於頻繁，請稍後再試"

    # 1. 取得 Member（優先用 default_member_id）
    member = get_member(bot_user.default_member_id)
    if not member:
        return "⚠️ 尚未設定 AI 角色，請聯繫管理員"

    # 2. 取得/建立對話 Session
    session = get_or_create_session(bot_user.id, member.id, msg.chat_id)

    # 3. 檢查 token 配額
    if session.total_output_tokens > member.monthly_token_limit:
        return "📊 本月 token 配額已用盡"

    # 4. 載入成員靈魂檔案
    soul = get_soul_content(member.slug)  # ← 讀取 .aegis/members/{slug}/soul.md

    # 5. 載入最近 N 條對話（從 ChatMessage）
    recent_messages = get_recent_messages(session.id, limit=10)

    # 6. 取得用戶可存取的專案清單
    accessible_projects = get_user_projects(bot_user.id)

    # 7. 建構 prompt（靈魂 + 歷史 + 專案 + 新訊息）
    prompt = build_chat_prompt(soul, recent_messages, msg.text, accessible_projects)

    # 7. 呼叫 AI（用 Member 的 Account）
    account = get_primary_account(member.id)
    result = await run_ai_task(
        task_id=0,  # 非卡片任務
        project_path=".",
        prompt=prompt,
        phase="CHAT",
        forced_provider=account.provider,
    )

    # 8. 儲存對話訊息
    save_message(session.id, "user", msg.text, result.get("input_tokens", 0), 0)
    save_message(session.id, "assistant", result["output"], 0, result.get("output_tokens", 0))

    # 9. 更新 Session 統計
    update_session_stats(session, result)

    return result["output"]


def build_chat_prompt(soul: str, history: list, user_message: str,
                      user_context: BotUserProject = None,
                      accessible_projects: list[Project] = None) -> str:
    """組合完整 prompt = 靈魂 + 用戶身份 + 專案範圍 + 歷史 + 新訊息"""
    lines = []

    # 靈魂人設（放最前面，定義角色）
    if soul:
        lines.append(soul.strip())
        lines.append("")

    # 用戶身份描述（讓 AI 知道在跟誰說話）
    if user_context:
        lines.append("## 當前用戶")
        if user_context.display_name:
            lines.append(f"姓名：{user_context.display_name}")
        if user_context.description:
            lines.append(f"身份描述：{user_context.description}")
        lines.append("")
        lines.append("請根據用戶的身份和權限範圍回答，用適當的稱呼和語氣。")
        lines.append("")

    # 用戶可存取的專案（讓 AI 知道範圍）
    if accessible_projects:
        lines.append("## 用戶可存取的專案")
        for p in accessible_projects:
            lines.append(f"- {p.name}（ID: {p.id}）")
        lines.append("")
        lines.append("回答問題時只能提供這些專案的資訊。")
        lines.append("")

    # 對話歷史
    if history:
        lines.append("## 對話歷史")
        for msg in history:
            role = "用戶" if msg.role == "user" else "你"
            lines.append(f"{role}：{msg.content}")
        lines.append("")

    # 當前訊息
    lines.append(f"用戶：{user_message}")
    lines.append("")
    lines.append("請以你的角色身份回應：")

    return "\n".join(lines)
```

---

## 八、實作優先級

### Phase 2.1：基礎用戶系統（2 天）
- [ ] BotUser Model（含 unique constraint、安全欄位）
- [ ] 自動建立 level=0 用戶
- [ ] 權限檢查 middleware（COMMAND_PERMISSIONS）
- [ ] 管理員自動識別（SystemSetting）
- [ ] ChannelBinding 新增 bot_user_id FK

### Phase 2.2：邀請碼驗證（1 天）
- [ ] InviteCode Model（含 allowed_projects, project_role）
- [ ] /invite 命令
- [ ] /verify 命令（含暴力破解保護）
- [ ] 過期/使用次數檢查
- [ ] 驗證失敗鎖定機制
- [ ] 驗證成功自動建立 BotUserProject

### Phase 2.3：用戶與專案管理（2 天）
- [ ] BotUserProject Model（用戶 ↔ 專案多對多）
- [ ] BotUserMember Model（用戶 ↔ 成員多對多）
- [ ] get_user_projects(), get_default_project(), can_user_create_card()
- [ ] /user list, info, grant, ban
- [ ] /me 命令
- [ ] /project list（列出用戶可存取的專案）
- [ ] Web UI 用戶管理頁面

### Phase 2.4：AI 對話（2 天）
- [ ] ChatSession + ChatMessage Model
- [ ] Router 非命令分支
- [ ] 整合 `get_soul_content(slug)` 載入靈魂檔案
- [ ] build_chat_prompt() 加入專案範圍限制
- [ ] `build_chat_prompt()` 組合 prompt
- [ ] 對話記憶（最近 10 條）
- [ ] Token 統計與限流

### Phase 2.5：進階功能（2 天）
- [ ] 細粒度權限（BotUserPermission）
- [ ] 專案存取限制
- [ ] /switch 切換角色
- [ ] 對話串流輸出
- [ ] 每分鐘/每日限流（Redis）

---

## 九、安全與邊緣情況

### 9.1 邀請碼安全

1. **隨機生成**：使用 `secrets.token_urlsafe(8)`，至少 12 字元
2. **限時限次**：預設 7 天過期、單次使用
3. **暴力破解保護**：
   - 連續 5 次驗證失敗 → 鎖定 30 分鐘
   - 記錄 `failed_verify_count` 和 `last_failed_at`
   - 鎖定期間所有 /verify 請求直接拒絕

```python
async def check_verify_lockout(bot_user: BotUser) -> bool:
    """檢查是否被鎖定"""
    if bot_user.locked_until and bot_user.locked_until > datetime.now(timezone.utc):
        return True
    if bot_user.failed_verify_count >= 5:
        # 計算鎖定時間
        if bot_user.last_failed_at:
            lockout_until = bot_user.last_failed_at + timedelta(minutes=30)
            if datetime.now(timezone.utc) < lockout_until:
                bot_user.locked_until = lockout_until
                return True
        # 超過鎖定時間，重置計數
        bot_user.failed_verify_count = 0
    return False
```

### 9.2 對話限流

| 限制類型 | 預設值 | 說明 |
|---------|--------|------|
| 每分鐘請求數 | 10 | 防止 spam |
| 每日訊息數 | 100 | 防止濫用 |
| 單訊息長度 | 2000 字 | 防止過長輸入 |
| 每月 token | 100K (L1) / 1M (L2) | Member 層級控制 |

```python
async def is_rate_limited(bot_user_id: int) -> bool:
    """檢查限流"""
    key = f"rate:{bot_user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)  # 1 分鐘視窗
    return count > 10
```

### 9.3 權限檢查 Middleware

```python
# router.py 中的權限檢查
COMMAND_PERMISSIONS = {
    "help": 0, "start": 0, "verify": 0,
    "status": 1, "card_list": 1,
    "run": 2, "stop": 2, "card_create": 2,
    "user": 3, "invite": 3, "grant": 3,
}

async def check_permission(bot_user: BotUser, command: str) -> bool:
    """檢查命令權限"""
    required_level = COMMAND_PERMISSIONS.get(command, 3)
    return bot_user.level >= required_level
```

### 9.4 用戶停用處理

當用戶被 ban（`is_active=False`）：
- 所有命令返回「帳號已停用」
- 自然語言對話不處理
- 不消耗任何資源

### 9.5 資源隔離

1. **專案存取**：透過 BotUserProject 控制（多對多關聯）
2. **Member 切換**：只能切換到 BotUserMember 中有記錄的
3. **對話隔離**：ChatSession 按 User × Member × Channel 隔離
4. **AI 回答範圍**：build_chat_prompt 加入 accessible_projects，限制 AI 只能回答用戶有權存取的專案

---

## 十、與 P1 的關係

### 10.1 概念對照

| P1（已完成） | P2（本計畫） |
|-------------|-------------|
| ChannelBinding | BotUser（用戶身份） |
| 通知綁定 | 權限控制 |
| /bind 命令 | /verify, /user 命令 |
| Message Bus | + AI 對話路由 |
| 命令處理 | + 權限 middleware |

### 10.2 ChannelBinding 與 BotUser 整合

**關係說明**：
- `ChannelBinding`：專注於**通知訂閱**（哪些頻道要收哪些事件）
- `BotUser`：專注於**用戶身份**（權限、對話、配額）

**整合方案**：在 ChannelBinding 新增 FK 指向 BotUser

```python
class ChannelBinding(SQLModel, table=True):
    # ... 原有欄位 ...

    # P2 新增：關聯到 BotUser（可選，向後相容）
    bot_user_id: Optional[int] = Field(default=None, foreign_key="botuser.id")
```

**流程變化**：
```
P1 /bind 流程：
InboundMessage → 建立 ChannelBinding

P2 整合後：
InboundMessage → 查/建 BotUser → 權限檢查 → 建立 ChannelBinding（帶 bot_user_id）
```

**好處**：
1. 通知訂閱仍可獨立運作（舊綁定不受影響）
2. 新綁定自動關聯用戶身份
3. 可追蹤「誰建立了哪些訂閱」

---

## 十一、三方審查報告（2026-03-09）

### 11.1 資料模型審查

**優點：**
- BotUser、BotUserMember、ChatSession/ChatMessage 設計完整
- UniqueConstraint 和索引設計正確
- ChannelBinding.bot_user_id FK 整合正確

**需修正：**

| 優先級 | 問題 | 建議 |
|--------|------|------|
| P0 | `core.py` 仍用舊版 `BotUserPermission`，缺少 `BotUserProject` 表 | 新增 BotUserProject 表，移除或保留 BotUserPermission 作補充 |
| P1 | `InviteCode` 缺少 `project_role` 欄位 | 補欄位：`project_role: str = Field(default="viewer")` |
| P2 | 外鍵缺少 `ON DELETE` 行為 | 定義刪除策略（CASCADE 或 SET NULL） |
| P3 | `ChatMessage.content` 無長度限制 | 加 `max_length=4000` |

### 11.2 安全性審查

**高風險（P0）：**

| 問題 | 建議 |
|------|------|
| `/card <id>` 無專案權限檢查，可越權查看他人卡片 | 所有涉及專案資源的操作必須驗證 `BotUserProject` |
| `/run` 無 `can_run_task` 檢查 | 執行任務前驗證專案權限 |

**中風險（P1）：**

| 問題 | 建議 |
|------|------|
| 邀請碼驗證無 race condition 防護 | 使用 `SELECT FOR UPDATE` 或原子操作 |
| 無 IP 層級暴力破解保護 | 加 IP 限流：同 IP 每小時最多 20 次 /verify |
| 邀請碼明文儲存 | 改用 SHA256 hash 儲存 |
| Redis 不可用時限流失效 | 加 in-memory fallback 或 fail-close |

**低風險（P2-P3）：**
- 無停用審計欄位 → 加 `ban_reason`, `banned_by`
- 對話內容明文儲存 → 定期清理或加密
- 無 GDPR 資料刪除機制 → 支援用戶資料刪除請求

### 11.3 實作可行性審查

**好消息：已完成 80%+**

| Phase | 狀態 | 剩餘工作 |
|-------|------|----------|
| 2.1 基礎用戶系統 | ✅ 90% | 補 migration |
| 2.2 邀請碼驗證 | ✅ 90% | 補 `project_role` 欄位 |
| 2.3 用戶與專案管理 | ⚠️ 60% | **新增 BotUserProject**、查詢函式 |
| 2.4 AI 對話 | ✅ 80% | 補專案範圍限制 |
| 2.5 進階功能 | ❌ 0% | 可延後（限流用 in-memory 先頂） |

**修正後時程：5 天（原 9 天）**

**限流替代方案（不依賴 Redis）：**
```python
from cachetools import TTLCache
rate_cache = TTLCache(maxsize=10000, ttl=60)

def is_rate_limited(bot_user_id: int) -> bool:
    key = f"rate:{bot_user_id}"
    count = rate_cache.get(key, 0) + 1
    rate_cache[key] = count
    return count > 10
```

### 11.4 關鍵待辦清單

```
☐ P0: 新增 BotUserProject 表（含 display_name, description, can_* 欄位）
☐ P0: 命令處理加專案權限檢查（/card, /run 等）
☐ P1: InviteCode 補 user_display_name, user_description, default_can_* 欄位
☐ P1: 補專案存取查詢函式（get_user_projects, get_user_context 等）
☐ P1: build_chat_prompt() 補 user_context 和 accessible_projects 參數
☐ P1: 邀請碼驗證加 race condition 防護
☐ P1: /invite 命令支援輸入用戶姓名和描述
☐ P2: 限流機制加 in-memory fallback
☐ P3: 補停用審計欄位（ban_reason, banned_by）
```

---

## 十二、變更記錄

| 版本 | 日期 | 變更 |
|------|------|------|
| v1.0 | 2026-03-09 | 初版規劃 |
| v1.1 | 2026-03-09 | Agent 審查後更新：<br>• BotUser 加 unique constraint<br>• 新增 BotUserMember 多對多表<br>• ChatContext 改為 ChatSession + ChatMessage<br>• 新增安全與邊緣情況章節<br>• 釐清 ChannelBinding 整合策略<br>• 完善命令權限矩陣 |
| v1.2 | 2026-03-09 | 整合成員 Profile：<br>• 新增 7.2 成員 Profile 整合章節<br>• 對話流程載入 soul.md 靈魂檔案<br>• 新增 build_chat_prompt() 範例 |
| v1.3 | 2026-03-09 | 用戶與專案多對多關聯：<br>• 將 BotUserPermission 改為 BotUserProject（更直觀）<br>• 新增 7.3 專案存取查詢章節<br>• build_chat_prompt() 加入 accessible_projects 參數<br>• 更新實作優先級 |
| v1.4 | 2026-03-09 | 三方審查報告：<br>• 資料模型審查：確認 BotUserProject 缺失<br>• 安全性審查：識別高風險專案權限漏洞<br>• 實作可行性：確認 80%+ 已完成，修正時程為 5 天<br>• 新增關鍵待辦清單（P0-P3 優先級）<br>• 新增限流替代方案（in-memory TTLCache） |
| v1.5 | 2026-03-09 | 自然語言身份描述：<br>• BotUserProject 新增 `display_name` 和 `description` 欄位<br>• 雙層權限控制：描述層（AI 理解）+ 硬性權限（程式碼強制）<br>• 新增 `can_access_sensitive` 權限欄位<br>• `build_chat_prompt()` 加入 `user_context` 參數<br>• InviteCode 新增 `user_display_name` 和 `user_description` 欄位<br>• 移除固定 role 欄位（viewer/member/admin），改用自然語言描述 |
| v1.6 | 2026-03-09 | UI 權限模板：<br>• 確認移除 BotUserProject.role 欄位<br>• 新增 UI 權限模板設計（訪客/成員/管理員）<br>• 模板只是 UI 快捷鍵，不存資料庫<br>• 保持資料模型乾淨，操作仍方便 |

---

*版本：v1.6*
*依賴：P1 多頻道架構*
