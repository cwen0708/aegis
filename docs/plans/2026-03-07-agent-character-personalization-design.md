# Agent Character Personalization Design

> Date: 2026-03-07
> Status: Approved

## Overview

為每位 AI 團隊成員（Member）建立獨立的個人化資料架構，包含身份描述（Soul）、專屬技能（Skills）、個人記憶（Memory），並改造任務調度流程，讓 AI 在執行任務時具備完整的角色上下文。

## Design Decisions

| 決策 | 選擇 | 理由 |
|------|------|------|
| 資料存放位置 | 全域 `~/.aegis/members/` | 角色跨專案共用 |
| Skill 格式 | 純 MD（CLAUDE.md 風格） | 直接注入 CLI，無需解析 |
| Skill 注入方式 | 全部複製到臨時資料夾 | 簡單，skill 數量不會太多 |
| 記憶寫入時機 | 即時短期 + 定期長期整理 | 完整覆蓋 |
| 記憶注入方式 | 只提供路徑，不塞內容 | 節省 token，AI 按需讀取 |
| 臨時工作區 | 每次任務建立，完成後銷毀 | 利用 CLI 原生行為 |
| Provider 相容 | 統一邏輯，切換檔名 | Claude: `CLAUDE.md` + `.claude/`，Gemini: `.gemini.md` + `.gemini/` |

## 1. Member Profile Directory Structure

```
~/.aegis/members/{member_slug}/
├── soul.md                      # 身份、人設、溝通風格
├── skills/                      # 純 MD 技能檔案
│   ├── fullstack-dev.md
│   └── code-review.md
└── memory/
    ├── short-term/              # 時間戳 MD（自動清理）
    │   └── 2026-03-07-1430.md
    └── long-term/               # 主題 MD（持久）
        └── project-patterns.md
```

`member_slug` 由 Member 模型的新增 `slug` 欄位提供（如 `xiao-jun`），對應資料夾名稱。

## 2. soul.md Format

```markdown
# 小筃 — 資深開發者

## 身份
你是 Aegis AI 開發團隊的資深全端工程師「小筃」。

## 專長
- Vue 3 Composition API + TypeScript
- Python FastAPI 後端
- 系統架構設計

## 工作風格
- 先讀現有程式碼再動手
- 小步提交、單一責任
- 繁體中文註解與 commit message
- 不自作主張加功能
```

## 3. Task Workspace (Temp Directory)

每次任務啟動時建立，完成後銷毀。

```
~/.aegis/workspaces/task-{card_id}/
├── CLAUDE.md (或 .gemini.md)
└── .claude/ (或 .gemini/)
    └── skills/
        ├── fullstack-dev.md
        └── ...
```

### CLAUDE.md 組成

一份檔案包含所有上下文：

```markdown
# 工作目錄
你的專案在 D:\github\some-project
所有程式碼修改都在那個目錄進行。

# 你的身份
{soul.md 內容}

# 記憶
你的個人記憶存放在：
~/.aegis/members/xiao-jun/memory/
- short-term/ 短期記憶（近期任務摘要）
- long-term/ 長期記憶（累積的經驗與模式）
需要回憶時可以去讀取。

# 本次任務
{卡片 content}
```

### Provider 差異

| | Claude CLI | Gemini CLI |
|---|---|---|
| 指令檔 | `CLAUDE.md` | `.gemini.md` |
| 技能目錄 | `.claude/skills/` | `.gemini/skills/` |

邏輯統一，只根據 provider 切換檔名和目錄名。

## 4. Task Dispatch Flow

```
Poller 偵測到 pending 卡片
    │
    ├─ 解析 member_id → 查到角色「小筃」(slug: xiao-jun)
    ├─ 解析 provider → "claude"
    │
    ▼
prepare_task_workspace(card_id, member, provider, project)
    │
    ├─ 建立 ~/.aegis/workspaces/task-{card_id}/
    ├─ 讀取 soul.md → 組裝 CLAUDE.md（soul + 記憶路徑 + 卡片內容）
    ├─ 複製 skills/ → .claude/skills/
    │
    ▼
run_ai_task(cwd=workspace_dir, prompt=...)
    │  ※ cwd 改為臨時工作區（原本是 project_path）
    │  ※ CLI 自動讀取 CLAUDE.md 和 .claude/skills/
    │
    ▼
任務完成
    │
    ├─ 更新卡片狀態（現有邏輯不變）
    ├─ 寫入角色短期記憶
    └─ cleanup_task_workspace() → 刪除臨時資料夾
```

### Key Changes to Existing Files

| 檔案 | 變更 |
|------|------|
| `runner.py` | `cwd` 改為 workspace dir；prompt 不再是卡片 content |
| `poller.py` | dispatch 前呼叫 `prepare_task_workspace()`，完成後呼叫 cleanup + 寫記憶 |
| `models/core.py` | Member 新增 `slug: str` 欄位 |
| `seed.py` | 建立角色資料夾 + soul.md + 初始 skills |

### New Modules

| 模組 | 職責 |
|------|------|
| `member_profile.py` | 角色資料讀取（soul, skills 路徑, memory 路徑） |
| `task_workspace.py` | 臨時工作區建立（組裝 CLAUDE.md, 複製 skills）與清理 |

## 5. Member Memory System

複用現有 `memory_manager.py` 的結構，路徑從系統級改為角色級。

### 短期記憶（任務完成時自動寫入）

```python
# 在 poller.py 的 _execute_and_update 中
write_member_short_term_memory(
    member_slug="xiao-jun",
    content=f"## 任務: {card_title}\n專案: {project_name}\n結果: {status}\n摘要: {output[:500]}"
)
```

檔名格式：`YYYY-MM-DD-HHmm.md`（與系統記憶一致）

### 長期記憶（CronJob 定期整理）

擴展現有「記憶整理」CronJob，除了系統記憶外，逐一處理每位角色的短期記憶 → 長期記憶。

### 清理

複用 `memory_manager.cleanup_short_term()`，路徑指向角色的 memory 目錄。

## 6. Seed Initialization

`seed.py` 新增 `seed_member_profiles()` 函式：

- 為小筃建立 `~/.aegis/members/xiao-jun/`：soul.md + skills/fullstack-dev.md
- 為小良建立 `~/.aegis/members/xiao-liang/`：soul.md + skills/code-review.md
- Member 模型新增 `slug` 欄位：`xiao-jun`, `xiao-liang`
- 自動建立 `memory/short-term/` 和 `memory/long-term/` 目錄

## 7. Fallback: No Member Assigned

當任務沒有指派 member 時（`member_id=None`）：
- 不建立臨時工作區
- 維持現有行為：`cwd=project_path`，直接傳卡片 content 作為 prompt
- 確保向後相容

## Files to Modify/Create

| 檔案 | 動作 | 說明 |
|------|------|------|
| `backend/app/core/member_profile.py` | 新增 | 角色資料讀取 |
| `backend/app/core/task_workspace.py` | 新增 | 臨時工作區管理 |
| `backend/app/core/runner.py` | 修改 | cwd 改為 workspace，調整 cmd 組裝 |
| `backend/app/core/poller.py` | 修改 | dispatch 前建立工作區，完成後清理+寫記憶 |
| `backend/app/core/memory_manager.py` | 修改 | 新增角色級記憶函式 |
| `backend/app/models/core.py` | 修改 | Member 加 slug 欄位 |
| `backend/seed.py` | 修改 | 建立角色資料夾 |
| `backend/tests/test_task_workspace.py` | 新增 | 工作區建立/清理測試 |
| `backend/tests/test_member_profile.py` | 新增 | 角色資料讀取測試 |
