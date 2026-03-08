# MD 檔案驅動任務系統 — 設計文件

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 將 Aegis 的看板卡片從純 SQLite 儲存，改為 MD 檔案作為 Source of Truth + SQLite 作為快取索引。

**日期：** 2026-03-06
**狀態：** 設計審查完成（已整合 review 修正）

---

## 1. 核心動機

| 需求 | 現況（純 SQLite） | 目標（MD 驅動） |
|------|------------------|----------------|
| 人類可讀 | 需透過 UI 或 SQL 查詢 | 直接打開 `.md` 檔閱讀 |
| AI 可讀寫 | 需透過 API 或 SQL | 直接讀寫檔案系統 |
| Git 友善 | 二進制 `.db` 檔，diff 無意義 | 每張卡片獨立 `.md`，可 diff/PR |
| 可攜帶性 | 已有（SQLite） | 更佳（純文字檔） |
| 外部整合 | 不適用 | MD 格式天然適合跨系統同步 |

---

## 2. 架構設計

### 2.1 方案：MD 為 Source of Truth + SQLite 為快取索引

```
┌─────────────────────────────────────────────────────┐
│                  使用者 / AI Agent                    │
│          直接讀寫 .md 檔案（編輯器、CLI）              │
└──────────────────────┬──────────────────────────────┘
                       │ 檔案系統
┌──────────────────────▼──────────────────────────────┐
│              {Project.path}/.aegis/cards/             │
│  card-000001.md  card-000002.md  card-000003.md ...   │
└──────────────────────┬──────────────────────────────┘
                       │ watchfiles 偵測變更
                       │ + API 寫入時主動同步
┌──────────────────────▼──────────────────────────────┐
│            CardIndex（local.db 內的快取表）            │
│  card_id | file_path | list_id | status | title      │
│  tags | created_at | updated_at | content_hash       │
│                                                      │
│  與 Project, Member, TaskLog 同庫（中央 local.db）    │
│  用途：快速查詢（board endpoint、poller pending 查詢） │
│  不儲存 content — 需要時從 MD 檔讀取                   │
└──────────────────────────────────────────────────────┘
```

### 2.2 資料流

**寫入流程（Write Path）：**
```
API/Poller/Runner 修改卡片
  → 寫入 MD 檔（atomic: temp + rename）
  → 更新 SQLite 索引（metadata only）
  → 廣播 WebSocket 事件
```

**讀取流程（Read Path）：**
```
Board 列表查詢（高頻）
  → 查 SQLite 索引（id, title, status, list_id, tags）
  → 不讀 MD 檔

卡片詳情查詢（低頻）
  → 查 SQLite 索引取得 file_path
  → 讀 MD 檔取得完整 content

Poller 查 pending 卡片（每 3 秒）
  → 查 SQLite 索引 WHERE status='pending'（回傳 card_id, list_id, file_path）
  → 對每張 pending 卡片：讀 MD 檔取得 content
  → 將 content 傳給 Runner（不在索引中儲存 content）
```

**外部修改偵測（File Watcher）：**
```
使用者/AI 直接修改 .md 檔
  → watchfiles 偵測到 mtime 變更
  → 解析 frontmatter → 更新 SQLite 索引
  → 廣播 WebSocket: card_updated
```

---

## 3. MD 檔案格式

### 3.1 Frontmatter Schema

```yaml
---
id: 42
list_id: 5
title: "修復 SQLite 連線池過期問題"
description: "這是一個嚴重的 bug"
status: idle          # idle | pending | running | completed | failed
tags:
  - Bug
  - Backend
created_at: "2026-03-06T12:34:56+08:00"
updated_at: "2026-03-06T12:34:56+08:00"
---
```

### 3.2 Body = content 欄位

Frontmatter 以下的所有內容即為原本的 `card.content`。

```markdown
---
id: 42
list_id: 5
title: "修復 SQLite 連線池過期問題"
description: "這是一個嚴重的 bug"
status: completed
tags:
  - Bug
  - Backend
created_at: "2026-03-06T12:34:56+08:00"
updated_at: "2026-03-06T14:00:00+08:00"
---

## 任務描述

調查 SQLite 連線池在高併發下過期的問題。

## AI Output (claude)

```
已修復 database.py 中的 pool_recycle 設定...
```
```

### 3.3 檔名規則

```
card-{id:06d}.md
```

範例：`card-000001.md`, `card-000042.md`, `card-001234.md`

- 零填充 6 位數，支援到 999,999 張卡片（含 cron 排程長期產生的卡片）
- 按 ID 排序時檔名自然排序
- ID 全域唯一（跨專案不重複），由 SQLite 全域計數器管理
- 避免使用 title 作為檔名（特殊字元、重複、變更問題）

### 3.4 目錄結構

```
backend/
└── local.db                    # 中央 DB（CardIndex + Project + Member + TaskLog + ...）

{ProjectA.path}/
└── .aegis/
    └── cards/
        ├── card-000001.md
        ├── card-000002.md
        └── card-000042.md

{ProjectB.path}/
└── .aegis/
    └── cards/
        ├── card-000010.md
        └── card-000011.md
```

- MD 檔案分散在各專案的 `.aegis/cards/` 目錄（source of truth）
- CardIndex 集中在 `local.db`（與現有 Project、Member、TaskLog 等表同庫）
- Card ID 全域唯一，跨專案不重複

---

## 4. 資料模型變更

### 4.1 移除：Card ORM 表

原本的 `Card` SQLModel 表將被移除。以下欄位改為 frontmatter：

| 原 Card 欄位 | 改放位置 | 說明 |
|-------------|---------|------|
| id | frontmatter `id` | 自增 ID，由系統管理 |
| list_id | frontmatter `list_id` | 所屬看板列 |
| title | frontmatter `title` | 卡片標題 |
| description | frontmatter `description` | 簡短描述 |
| content | MD body | frontmatter 以下的所有文字 |
| status | frontmatter `status` | 狀態枚舉 |
| created_at | frontmatter `created_at` | ISO 8601 |
| updated_at | frontmatter `updated_at` | ISO 8601 |
| tags | frontmatter `tags` (名稱列表) | 取代 CardTagLink join |

### 4.2 新增：CardIndex 快取表

```python
class CardIndex(SQLModel, table=True):
    """SQLite 快取索引 — 不是 source of truth"""
    card_id: int = Field(primary_key=True)
    project_id: int = Field(index=True)
    file_path: str                              # 相對於 Project.path
    list_id: int = Field(index=True)
    status: str = Field(index=True)             # 最關鍵的查詢欄位
    title: str
    description: Optional[str] = None
    tags_json: str = Field(default="[]")        # JSON array of tag names
    created_at: datetime
    updated_at: datetime
    content_hash: str = ""                      # SHA256, 用於偵測外部變更
    file_mtime: float = 0.0                     # os.stat mtime
```

### 4.3 保留不變的表

| 表 | 理由 |
|----|------|
| Project | 仍需 DB 管理（含 path 欄位） |
| StageList | 列表順序需要快速排序查詢 |
| Tag | 標籤 master 表（name → color 對應） |
| TaskLog | 執行記錄、token 用量統計，純查詢用途 |
| CronJob | 排程定義，非任務本身 |
| Member | 成員管理 |
| SystemSetting | 系統設定 |

### 4.4 移除的表

| 表 | 理由 |
|----|------|
| Card | 改為 MD 檔 |
| CardTagLink | tags 改存在 frontmatter 中 |

### 4.5 卡片狀態機

```
                    ┌──────────┐
         建立卡片 → │   idle   │
                    └────┬─────┘
                         │ trigger / 移動到 AI 列表
                    ┌────▼─────┐
         ┌────────→ │ pending  │ ←── cron_poller 建立
         │          └────┬─────┘
         │               │ poller 分派
         │          ┌────▼─────┐
         │          │ running  │ ←── AI 執行中
         │          └──┬────┬──┘
         │    成功 ─────┘    └───── 失敗/中止
         │    ┌────▼─────┐   ┌────▼─────┐
         │    │completed │   │  failed  │
         │    └──────────┘   └────┬─────┘
         │                        │ 重新觸發
         └────────────────────────┘
```

**孤兒 `running` 偵測**：啟動時檢查索引中所有 `status=running` 的卡片，
若 `running_tasks` 中無對應的進程，自動重設為 `failed`。

---

## 5. 核心模組設計

### 5.1 `card_file.py` — MD 檔讀寫引擎

```python
# backend/app/core/card_file.py
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import frontmatter

VALID_STATUSES = {"idle", "pending", "running", "completed", "failed"}

@dataclass
class CardData:
    """卡片資料結構（不依賴 SQLModel）"""
    id: int
    list_id: int
    title: str
    description: Optional[str]
    content: str              # MD body
    status: str
    tags: list[str] = field(default_factory=list)
    created_at: datetime
    updated_at: datetime

def read_card(file_path: Path) -> CardData:
    """解析 MD 檔 → CardData。frontmatter 格式錯誤時拋出 ValueError。"""

def write_card(file_path: Path, card: CardData) -> None:
    """CardData → 寫入 MD 檔（atomic: temp → fsync → rename）"""
    tmp = file_path.with_suffix('.md.tmp')
    content = serialize_card(card)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())  # 確保資料寫入磁碟
    tmp.replace(file_path)    # atomic rename

def card_file_path(project_path: str, card_id: int) -> Path:
    """回傳卡片檔案路徑: {project_path}/.aegis/cards/card-{id:06d}.md"""

def next_card_id(session: Session) -> int:
    """從 SQLite 全域計數器取得下一個 ID（避免併發衝突）"""
    # 使用 SELECT MAX(card_id) + 1 FROM card_index，在事務中鎖定
```

### 5.1.1 Frontmatter 驗證

```python
def validate_frontmatter(data: dict) -> list[str]:
    """驗證 frontmatter 必要欄位與型別，回傳錯誤訊息列表"""
    errors = []
    if "id" not in data or not isinstance(data["id"], int):
        errors.append("missing or invalid 'id' (must be int)")
    if "list_id" not in data or not isinstance(data["list_id"], int):
        errors.append("missing or invalid 'list_id' (must be int)")
    if "title" not in data or not isinstance(data["title"], str):
        errors.append("missing or invalid 'title' (must be str)")
    if data.get("status") not in VALID_STATUSES:
        errors.append(f"invalid 'status': {data.get('status')}")
    return errors
```

外部修改的 MD 檔若驗證失敗，file watcher 會記錄警告但**不更新索引**（避免髒資料進入系統）。

### 5.2 `card_index.py` — 索引快取管理

```python
# backend/app/core/card_index.py

def rebuild_index(project_id: int, project_path: str) -> int:
    """啟動時全量掃描 MD 檔 → 重建索引，回傳卡片數"""

def sync_card_to_index(card: CardData, project_id: int) -> None:
    """單張卡片寫入後更新索引"""

def remove_card_from_index(card_id: int) -> None:
    """卡片刪除時移除索引"""

def query_pending_cards(project_id: int = None) -> list[CardIndex]:
    """查 status='pending' — poller 用"""

def query_board(project_id: int) -> list[dict]:
    """查特定專案的所有卡片摘要 — board endpoint 用"""
```

### 5.3 `card_watcher.py` — 檔案變更偵測

```python
# backend/app/core/card_watcher.py

async def start_card_watcher():
    """
    使用 watchfiles 監控所有 Project 的 .aegis/cards/ 目錄。
    偵測到變更時：
    1. 解析被修改的 MD 檔
    2. 更新 SQLite 索引
    3. 廣播 WebSocket 事件
    """
```

---

## 6. API 變更

### 6.1 影響的 Endpoints

| Endpoint | 現行 | 改後 |
|----------|------|------|
| `GET /projects/{id}/board` | 查 Card 表 join StageList | 查 CardIndex 表（不變動 response 格式） |
| `GET /cards/{id}` | 查 Card 表 | 查 CardIndex 取得 file_path → 讀 MD 檔 |
| `POST /cards/` | INSERT Card | 寫 MD 檔 → sync 索引 |
| `PATCH /cards/{id}` | UPDATE Card | 讀 MD → 修改 → 寫 MD → sync 索引 |
| `DELETE /cards/{id}` | DELETE Card | 刪 MD 檔 → 刪索引 |
| `POST /cards/{id}/trigger` | UPDATE status | 讀 MD → 改 status → 寫 MD → sync 索引 |
| `POST /cards/{id}/abort` | UPDATE status+content | 讀 MD → 改 status+content → 寫 MD → sync 索引 |

**Response 格式完全不變** — 前端不需要任何修改。

### 6.2 新增 Endpoint

| Endpoint | 用途 |
|----------|------|
| `POST /api/v1/projects/{id}/reindex` | 手動觸發重建索引 |

### 6.3 廢棄的 Endpoint

| Endpoint | 處理 |
|----------|------|
| `GET /api/v1/cards/` | 移除（無前端使用，跨專案全域查詢無 MD 對應） |

---

## 7. 併發控制

### 7.1 風險分析

已識別的高風險併發場景：

| 場景 | 嚴重度 | 說明 |
|------|--------|------|
| Poller 改 status 同時 API 改 content | 高 | 兩者同時寫同一 MD 檔 |
| Runner 寫結果同時使用者移動卡片 | 高 | 內容可能遺失 |
| 3 個 Runner 同時更新不同卡片的索引 | 中 | SQLite WAL 模式可處理 |
| File watcher 觸發同時 API 寫入 | 中 | 可能重複更新索引 |

### 7.2 鎖策略：asyncio.Lock per Card

```python
# 全域鎖管理器
_card_locks: dict[int, asyncio.Lock] = {}

def get_card_lock(card_id: int) -> asyncio.Lock:
    """取得 per-card 的 asyncio.Lock。使用 setdefault 避免 TOCTOU 競爭。"""
    return _card_locks.setdefault(card_id, asyncio.Lock())

def cleanup_card_lock(card_id: int) -> None:
    """卡片刪除時清理鎖，避免記憶體洩漏。"""
    _card_locks.pop(card_id, None)
```

**為何用 asyncio.Lock 而非檔案鎖：**
- Aegis 是單進程 FastAPI（asyncio 事件循環）
- 所有寫入者（API、Poller、Runner callback）都在同一個 event loop
- asyncio.Lock 零開銷、無死鎖風險、跨平台
- 不需要 fcntl/msvcrt 檔案鎖（那是多進程場景）

**寫入模式：**
```python
async def update_card(card_id: int, project_path: str, project_id: int,
                      updater: Callable[[CardData], None]):
    """所有卡片修改都必須經過此函式（API、Poller、Runner callback）。"""
    async with get_card_lock(card_id):
        card = read_card(card_file_path(project_path, card_id))
        updater(card)
        card.updated_at = datetime.now(tz)
        write_card(card_file_path(project_path, card_id), card)
        sync_card_to_index(card, project_id)
```

> **重要**：Runner 的 `_execute_and_update` callback 也必須使用 `update_card()`，
> 不得直接寫入 MD 檔，否則會與使用者操作產生競爭。

### 7.3 Atomic 寫入

```python
def write_card(file_path: Path, card: CardData):
    """Atomic write: 寫入 temp → fsync → rename"""
    tmp = file_path.with_suffix('.md.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(serialize_card(card))
        f.flush()
        os.fsync(f.fileno())   # 確保磁碟持久化（防斷電遺失）
    tmp.replace(file_path)     # atomic rename (NTFS/ext4)
```

### 7.4 File Watcher 防抖（mtime 比對策略）

```python
async def on_file_changed(path: str):
    """
    watchfiles 偵測到檔案變更時觸發。
    使用 mtime 比對來區分「內部寫入」與「外部修改」：
    - 內部寫入後 sync_card_to_index 已更新 file_mtime
    - 若 file 的 mtime == index 的 file_mtime → 忽略（內部寫入）
    - 若 mtime 不同 → 外部修改 → 解析並更新索引
    """
    file_path = Path(path)
    current_mtime = file_path.stat().st_mtime

    # 查索引中記錄的 mtime
    card_id = parse_card_id_from_filename(file_path.name)
    indexed = get_card_index(card_id)
    if indexed and abs(indexed.file_mtime - current_mtime) < 0.01:
        return  # 內部寫入，mtime 已同步，忽略

    # 外部修改 → 驗證 + 更新索引
    try:
        card = read_card(file_path)
        errors = validate_frontmatter(card.__dict__)
        if errors:
            logger.warning(f"Invalid frontmatter in {path}: {errors}")
            return  # 不更新索引
        sync_card_to_index(card, project_id)
        await broadcast_event("card_updated", {"card_id": card.id})
    except Exception as e:
        logger.warning(f"Failed to parse {path}: {e}")
```

> **為何不用 path set**：watchfiles 在 Windows 上回傳的路徑格式（`\` vs `/`、大小寫）
> 可能與程式內部路徑不一致，導致比對失敗。mtime 比對完全避免此問題。

---

## 8. 遷移策略

### 8.1 漸進式遷移（推薦）

分三步驟，每步都可獨立部署：

**Step 1：加入 MD 寫入層（雙寫）**
- 保留 Card 表不動
- 每次 Card 寫入時，同步寫出 MD 檔
- MD 檔此時只是副本（不是 source of truth）
- 可驗證 MD 格式正確性

**Step 2：切換讀取層**
- Board endpoint 改從 CardIndex 讀取
- Card detail 改從 MD 檔讀取
- 仍保留 Card 表（fallback）

**Step 3：移除 Card 表**
- 刪除 Card ORM model
- 啟動時從 MD 檔重建 CardIndex
- File watcher 上線
- Card 表正式廢棄

### 8.2 資料遷移腳本

```python
# backend/migrate_cards_to_md.py
def migrate():
    """將現有 Card 表資料匯出為 MD 檔"""
    for project in session.exec(select(Project)).all():
        cards_dir = Path(project.path) / ".aegis" / "cards"
        cards_dir.mkdir(parents=True, exist_ok=True)

        cards = session.exec(
            select(Card).join(StageList)
            .where(StageList.project_id == project.id)
        ).all()

        for card in cards:
            tags = [t.name for t in card.tags]
            card_data = CardData(
                id=card.id, list_id=card.list_id,
                title=card.title, description=card.description,
                content=card.content, status=card.status,
                tags=tags,
                created_at=card.created_at, updated_at=card.updated_at
            )
            write_card(cards_dir / f"card-{card.id:06d}.md", card_data)
```

---

## 9. AEGIS 系統專案

### 9.1 概念

Aegis 本身作為一個內建專案存在於看板系統中，用來執行系統級排程任務。
與一般開發專案不同，AEGIS 專案沒有 Backlog/Planning/Developing 等開發階段，
只有 `Scheduled` 列表，專門承接排程產生的卡片。

### 9.2 Model 變更

**Project 表新增欄位：**
```python
class Project(SQLModel, table=True):
    # ... 現有欄位 ...
    is_system: bool = Field(default=False)   # 系統專案，前端禁止刪除/改名
```

**CronJob 表新增欄位：**
```python
class CronJob(SQLModel, table=True):
    # ... 現有欄位 ...
    is_system: bool = Field(default=False)   # 系統排程，前端禁止刪除
```

### 9.3 預設排程

| 排程 | Cron 表達式 | Provider | 用途 |
|------|-----------|----------|------|
| 心跳檢查 (Heartbeat) | `*/30 * * * *` | gemini | 每 30 分鐘產生一張卡片，AI 檢查系統狀態與未處理事件 |
| 每日狀態報告 (Daily Report) | `0 9 * * *` | gemini | 每天 09:00 產出昨日摘要（完成/失敗任務數、token 消耗） |
| 記憶整理 (Memory Consolidation) | `0 */4 * * *` | gemini | 每 4 小時回顧事件，整理短期/長期記憶（詳見 9.6） |

**執行流程：**
```
CronJob (*/30 * * * *) → 建立卡片到 AEGIS/Scheduled
  → Poller 偵測到 pending → 分派給 AI (gemini)
  → AI 收到 prompt + 系統指標（CPU/RAM/任務狀態）
  → AI 判斷 + 產出摘要 → 寫回卡片 content
  → 卡片 completed
```

**心跳 Prompt 範例：**
```
你是 Aegis 系統的心跳檢查 AI。以下是目前系統狀態：

## 系統指標
- CPU: {cpu_percent}%
- RAM: {mem_percent}% (可用 {mem_available_gb} GB)
- 運行中任務: {running_count}/{max_workstations}

## 待處理卡片
{pending_cards_summary}

## 最近失敗的任務
{recent_failures}

請判斷：
1. 系統是否健康？
2. 是否有需要關注的異常？
3. 是否建議暫停分派（系統過載）？

以 Markdown 格式回覆，簡潔扼要。
```

### 9.4 前端防護

- `is_system=true` 的 Project：隱藏刪除按鈕、禁止改名
- `is_system=true` 的 CronJob：隱藏刪除按鈕（可停用 `is_enabled=false`，但不能刪除）
- AEGIS 專案的 StageList 不可新增/刪除/重排
- 後端 API 也加防護：刪除/修改時檢查 `is_system`，回傳 403

### 9.5 卡片累積管理

心跳每 30 分鐘產生一張，一天 48 張，需要清理機制：

- `completed` 的心跳卡片保留期限由 SystemSetting `memory_short_term_days` 控制（預設 30 天）
- 超過保留期限的 `completed` 卡片自動歸檔（移到 MD 的 `archive/` 子目錄）
- `failed` 的卡片不自動清理（需要人工關注）
- 歸檔的卡片不在看板顯示，但 MD 檔保留可查閱

### 9.6 Memory 系統（記憶整理）

#### 概念

AEGIS 擁有自己的記憶系統，分為短期與長期記憶，以 MD 檔案儲存。
每 4 小時由排程喚醒 AI，回顧這段時間發生的事件，整理成記憶寫入對應目錄。

#### 目錄結構

```
{AEGIS.path}/
├── .aegis/cards/              # 排程產生的卡片
└── memory/
    ├── short-term/            # 短期記憶（事實、近期事件）
    │   ├── 2026-03-07-0800.md
    │   ├── 2026-03-07-1200.md
    │   └── 2026-03-07-1600.md
    └── long-term/             # 長期記憶（模式、決策、穩定知識）
        ├── system-patterns.md
        ├── team-performance.md
        └── recurring-issues.md
```

#### 短期記憶

每次記憶整理排程執行後產出一份，記錄這 4 小時的事實：

```markdown
---
timestamp: "2026-03-07T12:00:00+08:00"
period: "2026-03-07 08:00 ~ 12:00"
---

## 任務執行
- 完成 3 張卡片（Aegis Demo: 2, ProjectX: 1）
- 失敗 1 張：「修復 WebSocket 斷線問題」— timeout 超過 40 分鐘
- Token 消耗：Claude 12,340 tokens ($0.15), Gemini 8,200 tokens ($0.02)

## 系統狀態
- CPU 平均 45%，峰值 82%（10:30 左右，3 個任務同時執行）
- 無異常警報

## 值得注意
- WebSocket 修復任務已連續失敗 3 次，可能需要人工介入
```

- 檔名格式：`YYYY-MM-DD-HHmm.md`（取排程執行時間）
- 保留天數由 SystemSetting `memory_short_term_days` 控制（預設 30 天）
- 超過保留天數的短期記憶自動刪除（不歸檔，因為重要內容已升級到長期）

#### 長期記憶

AI 在整理短期記憶時，同時判斷是否有值得寫入長期記憶的模式：

```markdown
---
topic: "recurring-issues"
updated_at: "2026-03-07T12:00:00+08:00"
---

## WebSocket 斷線問題
- 首次出現：2026-03-05
- 已失敗 5 次，與高 CPU 負載相關
- 建議：降低 max_workstations 或加入 CPU 門檻

## Gemini Planning 效率
- 觀察期間：2026-03-01 ~ 2026-03-07
- Gemini 處理 Planning 階段平均耗時 45 秒，Claude 平均 120 秒
- 結論：Planning 階段維持使用 Gemini 是正確的
```

- 長期記憶是**累積更新**的：AI 讀取現有檔案 → 新增/修改段落 → 寫回
- 不自動刪除（除非使用者手動清理）
- 每個主題一個檔案，AI 自行決定分類

#### 記憶整理排程

| 排程 | Cron 表達式 | Provider | 用途 |
|------|-----------|----------|------|
| 記憶整理 (Memory Consolidation) | `0 */4 * * *` | gemini | 每 4 小時回顧事件，整理短期/長期記憶 |

**記憶整理 Prompt：**
```
你是 Aegis 系統的記憶管理 AI。請根據以下資料整理系統記憶。

## 過去 4 小時的事件
{recent_task_logs}

## 過去 4 小時的心跳報告摘要
{recent_heartbeat_summaries}

## 現有短期記憶（最近 7 天）
{short_term_memories}

## 現有長期記憶
{long_term_memories}

請執行：
1. **短期記憶**：用 Markdown 整理這 4 小時發生的重要事實（任務、異常、數據）
2. **長期記憶更新**：判斷是否有反覆出現的模式、值得記錄的趨勢或決策建議
   - 如果有，輸出需要新增或更新的長期記憶內容
   - 如果沒有，回覆「無需更新長期記憶」

回覆格式：
---SHORT_TERM---
（短期記憶 Markdown 內容）
---LONG_TERM---
（長期記憶更新，或「無需更新」）
---LONG_TERM_FILE---
（目標檔名，如 recurring-issues.md、team-performance.md）
```

#### 記憶寫入流程

```
CronJob (0 */4 * * *) → 建立卡片到 AEGIS/Scheduled
  → Poller 分派給 AI
  → cron_poller 注入：TaskLog + 心跳摘要 + 現有記憶
  → AI 回覆分隔格式
  → _execute_and_update 解析回覆：
      1. ---SHORT_TERM--- → 寫入 memory/short-term/YYYY-MM-DD-HHmm.md
      2. ---LONG_TERM--- → 讀取 + 更新 memory/long-term/{filename}.md
  → 卡片 completed
```

#### SystemSetting 新增項目

| Key | 預設值 | 說明 |
|-----|--------|------|
| `memory_short_term_days` | `30` | 短期記憶保留天數，超過自動刪除 |

此設定在 Settings 頁面可調整。

---

## 10. 效能評估

| 操作 | 現行（SQLite） | 改後（MD + Index） | 差異 |
|------|--------------|-------------------|------|
| Board 查詢 | ~1ms（SQL query） | ~1ms（SQL query on CardIndex） | 無差異 |
| Card 詳情 | ~0.5ms（SQL query） | ~2ms（index lookup + file read） | +1.5ms，可忽略 |
| Poller 查 pending | ~0.5ms | ~0.5ms（index query） | 無差異 |
| 建立卡片 | ~1ms（INSERT） | ~3ms（write file + update index） | +2ms，可忽略 |
| 狀態更新 | ~1ms（UPDATE） | ~4ms（read file + write file + index） | +3ms，可接受 |
| 啟動重建索引 | N/A | ~50ms/100 cards | 一次性成本 |

**結論**：效能影響可忽略。最熱的路徑（poller 查 pending）仍然是 SQL 索引查詢。

---

## 10. 不做的事情（YAGNI）

| 功能 | 理由 |
|------|------|
| MD 檔案的 Git 自動 commit | 與 git_safety.py 功能重疊，使用者自行管理 |
| 支援巢狀目錄結構 | 單一 `cards/` 目錄足夠，未來需要再加 |
| MD 檔內嵌圖片 | 現有立繪系統用獨立 uploads 目錄 |
| 即時雙向同步（Dropbox 式） | 超出目前範圍，未來再評估 |
| 支援非 MD 格式（YAML、JSON） | MD 是唯一格式 |
| 多進程寫入支援 | Aegis 是單進程架構 |

---

## 11. 前端影響

**零修改**。所有 API response 格式不變：
- `GET /projects/{id}/board` 回傳格式不變
- `GET /cards/{id}` 回傳格式不變
- WebSocket 事件格式不變

前端完全不知道後端從 SQLite 改成了 MD 檔。

---

## 12. 需新增的依賴

```
# backend/requirements.txt 新增
python-frontmatter>=1.1.0    # 解析 YAML frontmatter
```

已有但需明確列出：
- `watchfiles` — uvicorn[standard] 已內建
- `pyyaml` — 已安裝

---

## 13. 測試策略

| 測試類型 | 內容 |
|---------|------|
| 單元測試 | `card_file.py`：read/write 往返一致性、frontmatter 格式 |
| 單元測試 | `card_index.py`：rebuild、sync、query 正確性 |
| 整合測試 | API → MD 檔 → Index 完整流程 |
| 併發測試 | 多個 asyncio task 同時讀寫同一卡片 |
| 遷移測試 | 現有 DB 資料遷移後完整性驗證 |
| Watcher 測試 | 外部修改 MD 檔後索引自動更新 |

---

## 14. 實作順序（概要）

1. Model 變更 — Project / CronJob 加 `is_system` 欄位
2. `card_file.py` — MD 讀寫引擎 + CardData model
3. `card_index.py` — SQLite 索引 CRUD + rebuild
4. `migrate_cards_to_md.py` — 遷移腳本
5. 改寫 `routes.py` — API 層切換到 MD + Index + `is_system` 防護
6. 改寫 `poller.py` — Poller 切換到 MD + Index
7. 改寫 `cron_poller.py` — Cron 建卡改寫 MD（含 tags 寫入 frontmatter）+ 心跳 prompt 注入系統指標
8. `card_watcher.py` — File watcher 上線
9. AEGIS 系統專案 — seed 預設專案 + Scheduled 列表 + 3 個系統排程
10. Memory 系統 — 記憶整理排程的 prompt 注入 + 回覆解析 + MD 寫入
11. 前端 `is_system` 防護 — 隱藏刪除按鈕、禁止修改系統專案/排程
12. 前端 Settings 頁面 — 新增 `memory_short_term_days` 設定項
13. 短期記憶/心跳卡片清理 — 定期刪除超過保留天數的檔案
12. 移除 Card / CardTagLink ORM 表
13. 啟動時孤兒 `running` 狀態偵測 + 索引重建
14. 端到端測試 + 清理

---

## 15. 設計審查記錄

審查日期：2026-03-06

| # | 問題 | 嚴重度 | 修正措施 |
|---|------|--------|---------|
| C1 | `get_card_lock()` TOCTOU 競爭 | 高 | 改用 `dict.setdefault()` |
| C2 | File watcher path set 防抖在 Windows 不可靠 | 高 | 改用 mtime 比對 |
| C3 | `next_card_id()` 目錄掃描併發衝突 | 高 | 改用 SQLite 全域計數器 |
| C4 | Poller 讀 content 流程未明確 | 高 | 補充：index 查 pending → 讀 MD 取 content |
| C5 | Runner callback 未經 lock 寫入 | 高 | 強制所有寫入經過 `update_card()` |
| I1 | Card ID 全域 vs 專案級歧義 | 重要 | 保持全域唯一 ID |
| I2 | 缺少狀態機 + 孤兒 running 偵測 | 重要 | 加入狀態圖 + 啟動偵測 |
| I3 | 4 位數零填充不夠 | 重要 | 改為 6 位數 |
| I4 | cron_poller 建卡的 CardTagLink 遷移 | 重要 | tags 直接寫入 frontmatter |
| I5 | content_hash 定義但未使用 | 建議 | 保留用於 rebuild_index 偵測陳舊索引 |
| I6 | Atomic rename 無 fsync | 建議 | 加入 os.fsync() |
| I7 | Frontmatter 驗證缺失 | 重要 | 加入 validate_frontmatter() |
| S3 | Lock dict 記憶體洩漏 | 建議 | 加入 cleanup_card_lock() |
| S4 | GET /cards/ 全域端點無對應 | 建議 | 標記為廢棄 |
