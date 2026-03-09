# Aegis P2 Bot 用戶與權限系統

> 狀態：規劃中
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

| 命令 | L0 | L1 | L2 | L3 |
|------|----|----|----|----|
| /help, /start | ✅ | ✅ | ✅ | ✅ |
| /verify | ✅ | - | - | - |
| /status | ❌ | ✅ | ✅ | ✅ |
| /card list | ❌ | ✅ | ✅ | ✅ |
| 自然語言對話 | ❌ | ✅ | ✅ | ✅ |
| /run, /stop | ❌ | ❌ | ✅ | ✅ |
| /card create | ❌ | ❌ | ✅ | ✅ |
| /user 管理 | ❌ | ❌ | ❌ | ✅ |
| /invite | ❌ | ❌ | ❌ | ✅ |

---

## 四、資料模型

### 4.1 BotUser（新增）

```python
class BotUser(SQLModel, table=True):
    """Bot 用戶（真人）"""
    id: Optional[int] = Field(default=None, primary_key=True)

    # 平台身份
    platform: str = Field(index=True)       # telegram, line...
    platform_user_id: str = Field(index=True)
    username: Optional[str] = None          # 顯示名稱

    # 權限
    level: int = Field(default=0)           # 0-3
    is_active: bool = Field(default=True)

    # 綁定
    default_member_id: Optional[int] = Field(default=None, foreign_key="member.id")

    # 時間
    created_at: datetime
    last_active_at: Optional[datetime] = None
```

### 4.2 BotUserPermission（新增）

```python
class BotUserPermission(SQLModel, table=True):
    """細粒度權限控制"""
    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id")

    # 權限類型
    permission: str         # "view", "execute", "create", "admin"

    # 資源範圍（可選）
    resource_type: Optional[str] = None   # "project", "member"
    resource_id: Optional[int] = None     # 具體 ID，null = 全部
```

### 4.3 InviteCode（新增）

```python
class InviteCode(SQLModel, table=True):
    """邀請碼"""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "CUSTA2024"

    # 配置
    target_level: int = Field(default=1)
    target_member_id: Optional[int] = None
    allowed_projects: Optional[str] = None      # JSON: [1, 2, 3]

    # 使用限制
    max_uses: int = Field(default=1)
    used_count: int = Field(default=0)
    expires_at: Optional[datetime] = None

    # 元資料
    created_by: int         # 建立者 BotUser ID
    created_at: datetime
    note: str = ""          # "給客戶A用"
```

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

### 7.1 對話上下文

```python
class ChatContext(SQLModel, table=True):
    """對話上下文（User × Member）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id")
    member_id: int = Field(foreign_key="member.id")

    # 對話記錄（最近 N 條）
    messages: str = "[]"    # JSON: [{role, content, timestamp}]

    # 元資料
    created_at: datetime
    updated_at: datetime
```

### 7.2 對話處理

```python
async def handle_chat(msg: InboundMessage, bot_user: BotUser):
    """處理自然語言對話"""

    # 1. 取得 Member
    member = get_member(bot_user.default_member_id)

    # 2. 取得/建立對話上下文
    context = get_or_create_context(bot_user.id, member.id)

    # 3. 建構 prompt
    prompt = build_prompt(member, context, msg.text)

    # 4. 呼叫 AI（用 Member 的 Account）
    account = get_primary_account(member.id)
    result = await run_ai_task(
        task_id=0,  # 非卡片任務
        project_path=".",
        prompt=prompt,
        phase="CHAT",
        forced_provider=account.provider,
    )

    # 5. 更新上下文
    update_context(context, msg.text, result)

    # 6. 回傳回應
    return result["output"]
```

---

## 八、實作優先級

### Phase 2.1：基礎用戶系統（2 天）
- [ ] BotUser Model
- [ ] 自動建立 level=0 用戶
- [ ] 權限檢查 middleware
- [ ] 管理員自動識別（SystemSetting）

### Phase 2.2：邀請碼驗證（1 天）
- [ ] InviteCode Model
- [ ] /invite 命令
- [ ] /verify 命令
- [ ] 過期/使用次數檢查

### Phase 2.3：用戶管理（1 天）
- [ ] /user list, info, grant, ban
- [ ] /me 命令
- [ ] Web UI 用戶管理頁面

### Phase 2.4：AI 對話（2 天）
- [ ] ChatContext Model
- [ ] Router 非命令分支
- [ ] Member 人設 prompt
- [ ] 對話記憶（最近 10 條）

### Phase 2.5：進階功能（2 天）
- [ ] 細粒度權限（BotUserPermission）
- [ ] 專案存取限制
- [ ] /switch 切換角色
- [ ] 對話串流輸出

---

## 九、安全考量

1. **邀請碼**：隨機生成、限時、限次
2. **權限檢查**：每個命令執行前驗證
3. **資源隔離**：客戶只能看自己的專案
4. **API 配額**：Member 層級控制，防止濫用
5. **日誌追蹤**：記錄所有操作，可審計

---

## 十、與 P1 的關係

| P1（已完成） | P2（本計畫） |
|-------------|-------------|
| ChannelBinding | BotUser（用戶身份） |
| 通知綁定 | 權限控制 |
| /bind 命令 | /verify, /user 命令 |
| Message Bus | + AI 對話路由 |
| 命令處理 | + 權限 middleware |

---

*版本：v1.0*
*依賴：P1 多頻道架構*
