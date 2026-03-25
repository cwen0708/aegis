# Aegis .aegis 目錄結構 — 完整規劃

> 運行時根目錄：`/home/cwen0708/.local/aegis/.aegis/`
> 所有 AI 成員的身份、技能、記憶、工作空間、會議紀錄都在這裡。

## 完整目錄樹

```
.aegis/
├── members/                          # 成員身份（永久，版本控制）
│   └── {member_slug}/
│       ├── soul.md                   # 身份定義（角色、專長、風格）
│       ├── mcp.json                  # MCP 工具設定
│       ├── skills/                   # 成員專屬技能
│       │   └── *.md
│       └── memory/                   # 成員記憶
│           ├── short-term/           # 近期任務摘要（自動寫入）
│           │   └── {date}-*.md
│           └── long-term/            # 累積經驗（手動或 AI 整理）
│               └── *.md
│
├── shared/                           # 共用資源（所有成員都有）
│   └── skills/                       # 共用技能
│       ├── aegis-api.md              # 內部 API 工具
│       ├── ask-member.md             # 詢問隊友（Agent-to-Agent）
│       ├── line-send.md              # LINE Push API
│       ├── media-response.md         # 媒體回應
│       ├── team.md                   # 團隊資訊
│       └── collaboration.md          # 協作規範
│
├── chat-workspaces/                  # 對話工作空間（持久，ProcessPool cwd）
│   └── {member_slug}/
│       ├── telegram:{user_id}:{slug}/    # Telegram 用戶對話
│       │   ├── CLAUDE.md                 # soul + 用戶身份 + 安全限制
│       │   ├── .claude/settings.json
│       │   ├── .claude/skills/ → symlink
│       │   └── .mcp.json → symlink
│       ├── onestack:{user}:{slug}/       # OneStack 用戶對話
│       ├── agent:{from}:{slug}/          # 其他 AI 成員的 ask_member 對話
│       └── meeting/                      # 會議 session（唯一）
│           ├── CLAUDE.md
│           ├── .claude/skills/ → symlink
│           └── .mcp.json → symlink
│
├── workspaces/                       # 任務工作空間（臨時，用完刪除）
│   └── task-{card_id}/
│       ├── CLAUDE.md                 # soul + 安全限制 + 任務內容
│       ├── .claude/skills/           # 複製（非 symlink）
│       ├── .mcp.json                 # 複製
│       ├── .gitconfig                # GitHub PAT credential
│       ├── .git → symlink            # 指向專案 .git
│       └── {project_files} → symlink # 指向專案原始碼
│
├── meetings/                         # 會議紀錄（新增，持久保存）
│   ├── standup-2026-03-25.md         # 站會
│   ├── standup-2026-03-26.md
│   └── review-{topic}-{date}.md     # Code Review / 需求討論
│
├── cards/                            # 卡片 MD 檔案
│   └── card-{id}.md
│
├── abort/                            # Abort 信號（檔案存在 = 中止請求）
│   └── {card_id}                     # 空檔案
│
└── secrets/                          # 機密設定
    └── nas.env                       # NAS 環境變數
```

## chat_key 命名規則

| 場景 | chat_key 格式 | 範例 |
|------|--------------|------|
| Telegram 對話 | `telegram:{user_id}:{member_slug}` | `telegram:7362884113:xiao-mu` |
| OneStack 對話 | `onestack:{user}:{slug}:{member_slug}` | `onestack:os:xiao-zhen:xiao-zhen` |
| Agent 諮詢 | `agent:{from_slug}:{target_slug}` | `agent:xiao-mu:xiao-liang` |
| 會議 | `meeting` | `meeting`（每成員唯一） |
| Web 對話 | `web:{user_id}:{member_slug}` | `web:1:xiao-mu` |

## 目錄生命週期

| 目錄 | 建立時機 | 刪除時機 | 數量上限 |
|------|---------|---------|---------|
| `members/{slug}/` | 管理員建立成員 | 手動刪除 | = 成員數（9） |
| `chat-workspaces/{slug}/{key}/` | 首次對話 | 不刪（持久） | = 成員 × 通道數 |
| `chat-workspaces/{slug}/meeting/` | 首次開會 | 不刪（持久） | = 成員數（9） |
| `workspaces/task-{id}/` | Worker 建立 | 任務完成後刪 | ≤ 併發任務數（3） |
| `meetings/*.md` | 每場會議 | 可定期歸檔 | 隨時間累積 |
| `cards/*.md` | 建卡片 | 卡片刪除時 | 隨時間累積 |

## 會議系統架構

### ConversationRoom（站會/討論）

```
CronJob 或手動觸發
  ↓
Coordinator 建立 meetings/{id}.md（開場白 + 系統狀態）
  ↓
┌─ 輪流制 ──────────────────────────┐   ┌─ 主持人制 ──────────────────────┐
│ 固定順序：A → B → C → 總結        │   │ 主持人判斷下一個誰講            │
│ rounds=1：每人一次（站會）        │   │ [NEXT:slug] 問題                │
│ rounds=3：每人三次（深度討論）    │   │ [DONE] 結束                     │
└───────────────────────────────────┘   └─────────────────────────────────┘
  ↓（兩種模式都走同一個底層）
process_pool.send_message(
    chat_key="meeting",
    member_id=當前發言者,
    message="請讀取 meetings/{id}.md，輪到你發言，追加回應。"
)
  ↓
AI 讀取 meetings/{id}.md → 看到所有人的發言 → 追加自己的回應
  ↓
Coordinator 讀取 AI 回應 → 追加到 meetings/{id}.md → 下一位
```

### ask_member（一對一即時諮詢）

```
AI 成員 A 在執行任務中遇到問題
  ↓
curl POST /api/v1/agent-chat/ask
  { target: "xiao-liang", question: "...", from_member: "xiao-mu" }
  ↓
Aegis API → resolve_member → ensure_chat_workspace(chat_key="agent:xiao-mu:xiao-liang")
  ↓
process_pool.send_message → 小良的 session 回應 → 回傳給小牧
```

### 群聊 UI（構想，低優先）

```
辦公室頁面 → 「啟動會議」按鈕
  ↓
前端顯示：左右成員列表 + 底部輸入框
  ↓
使用者輸入主題 → 作為起始 prompt 寫入 meetings/{id}.md
  ↓
點擊成員頭像 → 呼叫 ask_member API → 回應顯示在對話串
  ↓
發言完可能隨機 @ 其他成員繼續
```

## 實施優先級

| 階段 | 項目 | 狀態 | 說明 |
|------|------|------|------|
| **P0** | ask_member API | ✅ 已完成 | `POST /api/v1/agent-chat/ask` |
| **P0** | ask-member.md skill | ✅ 已完成 | 所有成員自動擁有 |
| **P1** | ConversationRoom coordinator | 待做 | 取代卡片流轉站會，省 ~66% token |
| **P1** | `meetings/` 目錄 + 紀錄格式 | 待做 | coordinator 的前置 |
| **P2** | CronJob 整合 | 待做 | cron_poller 觸發 coordinator 而非建卡片 |
| **P3** | 群聊 UI | 構想 | 辦公室頁面的會議按鈕 |

## 與 Executor 模組的關係

```
executor/
├── providers.py    ← ask_member 用 build_command (如果走 CLI fallback)
├── auth.py         ← ask_member 用 inject_auth_env
├── context.py      ← ask_member 用 resolve_member_for_chat + effective_model
├── config_md.py    ← ensure_chat_workspace 用 build_config_md
├── emitter.py      ← 未來 meeting 可加 WebSocketTarget 即時推前端
└── heartbeat.py    ← 長時間 meeting 可加心跳
```

所有新功能都建在 executor + ProcessPool + chat_workspace 之上，不需要新的基礎設施。
