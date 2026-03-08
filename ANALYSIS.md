# Aegis 專案深度分析報告

## 1. 專案定位與目標

### 1.1 核心定位
**Aegis（神盾）** 是一個 **AI 開發團隊調度與任務管理平台**，專為多重 AI 代理（Claude、Gemini）設計的原生工作環境。它不只是看板工具，而是一個完整的 **AI 驅動工作流編排系統**。

### 1.2 戰略目標
- 成為 AI 開發團隊的 **調度中心**，統一管理多個 AI 代理的任務執行
- 提供 **標籤驅動派遣**：根據卡片標籤自動路由至合適的 AI 引擎
- 建立 **完整的任務履歷與成本追蹤**：跨專案、跨引擎的 Token 消耗分析
- 支援 **多渠道整合**（未來）：Telegram/LINE 遠端建卡、狀態查詢、任務中止

### 1.3 使用者對象
- **AI 應用開發團隊**（多個 Claude/Gemini 帳號協作）
- **自動化開發者**（需要定時執行 AI 任務的場景）
- **研究人員**（分析 AI 代理行為與成本的需求）

---

## 2. 核心功能與架構

### 2.1 主要功能模塊

| 功能名稱 | 描述 | 技術實現 |
|--------|------|--------|
| **Virtual Office** | 像素風虛擬辦公室，AI 角色在工作台工作、茶水間閒晃 | Phaser 3 遊戲引擎 + A* 尋路動畫 |
| **Kanban Board** | 拖曳式看板（Backlog → Planning → Developing → Verifying → Done） | Vue 3 + vuedraggable |
| **AI Portrait Generation** | 上傳真人照片，Gemini 分析特徵後生成日系動漫立繪 | Gemini Flash + Imagen + rembg |
| **Real-time Monitoring** | 每 5 秒廣播 CPU/RAM/Disk 指標及運行任務狀態 | WebSocket + psutil |
| **Multi-AI Routing** | Planning → Gemini，Developing → Claude（可配置） | 階段路由表 + 環境檢測 |
| **Log Streaming** | AI subprocess 的 stdout 即時串流至前端終端機 | 非同步 subprocess + WebSocket |
| **Slot-based Concurrency** | 最多 3 個 AI 任務並行（asyncio.Semaphore） | 全域互斥鎖 + 工作台管理 |
| **Cron Scheduler** | 內建排程引擎，支援 cron expression | croniter + 後台 poller |
| **Claude Usage Tracking** | 多帳號 OAuth 用量查詢（5h/7d、Sonnet/Opus 分類） | Claude OAuth API 集成 |
| **Git Safety** | AI 執行前自動 stash/branch，失敗時回滾 | GitPython（已實現，未使用） |
| **MD-driven Tasks** | 卡片以 Markdown 檔案為 Source of Truth，SQLite 為索引 | watchfiles + frontmatter 解析 |
| **Member Personalization** | 每個 AI 成員有獨立的 Soul（人設）、Skills、Memory | 檔案系統 + 臨時工作區注入 |

### 2.2 系統架構

```
┌────────────────────────────────────────────────────────────┐
│                    Vue 3 Frontend                           │
│  Office  Dashboard  Kanban  CronJobs  Team  Agents  Settings│
│  (Phaser 3 pixels)     ←─── Pinia ──→        WebSocket      │
└─────────────────────────┬──────────────────────────────────┘
                          │ HTTP / WS
┌─────────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend                           │
│  REST API │ WebSocket Broadcast │ Task Poller              │
│  ┌──────────────────────────────────────────────┐          │
│  │         Agent Runner (run_ai_task)            │          │
│  │    asyncio.Semaphore (max 3 concurrent)      │          │
│  │    Claude CLI ←→ subprocess ←→ Gemini CLI    │          │
│  └──────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────┐          │
│  │     Portrait Generator (Gemini + Imagen)     │          │
│  │              + rembg 去背                     │          │
│  └──────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────┐          │
│  │  Memory & Skill Management                   │          │
│  │  (~/.aegis/members/{slug}/soul.md + skills/)│          │
│  └──────────────────────────────────────────────┘          │
│                                                             │
│  SQLite (local.db): Projects, Cards, Members, CronJobs    │
│  MD Files: {project}/.aegis/cards/*.md (source of truth)   │
│  File Watcher: watchfiles for auto-sync                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 任務執行流程

```
使用者移動卡片到 "Planning"
    ↓
Card 狀態 → "pending"
    ↓
Poller (1s 輪詢) 檢測 pending 卡片
    ↓
Runner 獲取信號量槽位 (最多 3 個)
    ↓
加載成員 Soul + Skills + Memory
    ↓
構建臨時工作目錄 (~/.aegis/workspaces/task-{card_id}/)
    ↓
生成 CLAUDE.md 或 .gemini.md（完整上下文）
    ↓
調用 `claude -p "{prompt}"` 或 `gemini -p "{prompt}"`
    ↓
即時串流 stdout → WebSocket → 前端終端機
    ↓
完成 → 更新 MD 檔狀態 → SQLite 同步 → 廣播完成事件
    ↓
前端自動刷新看板 + toast 通知
```

### 2.4 資料存儲層設計

**三層架構：**

1. **MD 檔案層（Source of Truth）**
   - 路徑：`{project_path}/.aegis/cards/card-{id:06d}.md`
   - 格式：Frontmatter + Markdown body
   - 用途：人類可讀、AI 可直接編輯、Git 友善

2. **SQLite 索引層（快取 + 查詢加速）**
   - 表：`CardIndex`（id, file_path, list_id, status, title, tags_json, content_hash）
   - 查詢場景：看板列表查詢（不讀 MD）、Poller pending 查詢
   - 不存儲 content（需時才讀 MD）

3. **ORM 層（向後相容）**
   - 表：`Project, StageList, Card, Tag, Member, CronJob, SystemSetting`
   - 用途：Web API 相容性、關聯查詢
   - 狀態：漸進遷移中（Card 與 MD 檔雙寫）

---

## 3. 技術棧

### 3.1 後端（Python FastAPI）

| 層級 | 技術 | 版本 | 用途 |
|------|------|------|------|
| **框架** | FastAPI | 0.110.0 | REST API + WebSocket + 非同步支持 |
| **伺服器** | Uvicorn | 0.27.1 | ASGI 伺服器 |
| **ORM** | SQLModel | 0.0.16 | SQLAlchemy + Pydantic 混合 |
| **資料庫** | SQLite | 內建 | 本地檔案資料庫 |
| **任務排程** | croniter | 2.0.0 | Cron 表達式解析與計算 |
| **AI API** | google-genai | 1.0.0 | Gemini API 客戶端 |
| **圖像處理** | rembg + Pillow | 2.0.50+ | 自動去背 |
| **檔案解析** | python-frontmatter | 1.1.0 | Markdown frontmatter 解析 |
| **系統監控** | psutil | 5.9.0+ | CPU/RAM/磁碟指標 |
| **Git 集成** | GitPython | — | Git 操作（已實現，未使用） |
| **認證** | python-jose | 3.3.0 | JWT（未使用） |
| **測試** | pytest + pytest-asyncio | 8.0+ | 單元測試框架 |

**核心模塊（後端）：**
- `runner.py` (242 行) — AI 任務執行引擎
- `poller.py` (>100 行) — 待執行卡片掃描分派
- `cron_poller.py` — Cron 排程觸發器
- `card_file.py` — MD 檔案讀寫引擎
- `card_index.py` — SQLite 索引管理
- `card_watcher.py` — 檔案系統監視
- `portrait_generator.py` — 頭像生成（Gemini + rembg）
- `claude_usage.py` — Claude OAuth 用量查詢
- `ws_manager.py` — WebSocket 廣播管理
- `telemetry.py` — 系統指標收集
- `routes.py` (1395 行) — 所有 REST 端點

### 3.2 前端（Vue 3 + TypeScript + Vite）

| 層級 | 技術 | 版本 | 用途 |
|------|------|------|------|
| **框架** | Vue 3 | 3.5.25 | Composition API |
| **語言** | TypeScript | 5.9.3 | 類型安全 |
| **構建** | Vite | 7.3.1 | 快速開發伺服器 + 生產構建 |
| **狀態管理** | Pinia | 3.0.4 | 輕量級狀態管理 |
| **路由** | Vue Router | 5.0.3 | 單頁應用路由 |
| **樣式** | Tailwind CSS 4 | 4.2.1 | 原子 CSS |
| **遊戲引擎** | Phaser 3 | 3.90.0 | 2D 像素遊戲（Virtual Office） |
| **圖標** | lucide-vue-next | 0.576.0 | 向量圖標庫 |
| **拖放** | vuedraggable + @dnd-kit/vue | 4.1.0 + 0.3.2 | 看板拖曳 |
| **增強** | @vueuse/core | 14.2.1 | Vue 組合式函數集 |
| **測試** | vue-tsc | 3.1.5 | TypeScript 類型檢查 |

**核心頁面（前端）：**
- `Office.vue` — Phaser 3 虛擬辦公室 + 地圖編輯器
- `Kanban.vue` — 看板管理（最複雜，683 行）
- `Dashboard.vue` — 系統指標 + Claude 用量
- `Team.vue` — 成員管理 + 頭像生成
- `Agents.vue` — AI 代理狀態監控
- `CronJobs.vue` — 排程任務 CRUD
- `Settings.vue` — 系統設定（時區、Gemini API Key）

**核心組件：**
- `CharacterDialog.vue` — AVG 風格對話框
- `OfficeEditor.vue` — 辦公室地圖編輯器
- `TerminalViewer.vue` — 任務日誌終端
- `ToastNotification.vue` — 通知提示
- `ConfirmDialog.vue` — 確認對話框

**遊戲模塊（src/game/）：**
- `OfficeScene.ts` — Phaser 主場景 + A* 尋路
- `EditorScene.ts` — 地圖編輯場景
- `layoutManager.ts` — 佈局序列化/反序列化
- `furnitureData.ts` — 家具配置
- `defaultLayout.ts` — 預設辦公室佈局
- `pathfinding.ts` — A* 演算法

### 3.3 部署配置

**開發模式：**
```bash
# 後端
cd backend && venv\Scripts\python.exe -m uvicorn app.main:app --reload

# 前端
cd frontend && pnpm dev  # Vite dev server on :5173

# 或一鍵啟動
dev.bat
```

**生產模式：**
```bash
start-aegis.bat
# 自動：
# 1. npm run build（前端）
# 2. 啟動後端 uvicorn（:8899）
# 3. 啟動前端靜態服務（npx serve）
```

**GCP 部署（claude-pm-server）：**
- HTTP 代理：https://aegis.yooliang.com（Cloudflare）
- 本機路徑：/home/cwen0/repos/Aegis/
- systemd 服務：aegis
- 重啟命令：`sudo systemctl restart aegis`

---

## 4. 優點

### 4.1 架構層面

1. **MD 檔案驅動 + SQLite 索引**
   - Source of Truth 是可讀文本，不是二進制 DB
   - 支援 Git diff/PR，方便代碼審查
   - AI 和人類都能直接編輯檔案
   - 整個資料夾可攜帶至任何環境

2. **完整的 AI 代理上下文注入**
   - 成員 Soul（人設）+ Skills（技能） + Memory（記憶）
   - 臨時工作區 (`~/.aegis/workspaces/task-{id}/`) 自動生成 CLAUDE.md
   - Claude 和 Gemini 支援不同的指令檔格式，邏輯統一
   - 記憶系統分短期（自動清理）與長期（持久）

3. **多 AI 引擎智能路由**
   - 標籤驅動派遣：`[Planning]` → Gemini，`[Developing]` → Claude
   - 支援環境檢測自動選擇
   - 易於擴展其他引擎（Anthropic、OpenAI）

4. **並行執行與資源控制**
   - asyncio.Semaphore 限制最多 3 個 AI 任務
   - 每個成員同時只能佔用 1 個工作台（busy_members 集合）
   - 工作台數量可動態調整

5. **實時監控與互動**
   - WebSocket 每 5 秒廣播系統指標 + 運行任務
   - Log streaming：AI 的 stdout 即時投射至前端終端
   - AVG 風格對話框展示任務履歷
   - Pixel art 虛擬辦公室的沉浸感

6. **完整的成本追蹤**
   - Claude OAuth 用量查詢（5h/7d、Sonnet/Opus 分類、超額信用）
   - 任務執行記錄包含 Token 消耗與 USD 成本
   - 跨帳號、跨引擎的成本分析

7. **內置排程與自動化**
   - Cron 引擎支援 cron 表達式（如 `0 9 * * MON`）
   - 可暫停/恢復全局 Poller
   - 支援按專案暫停排程

8. **開發友善**
   - 清晰的項目結構：backend/frontend 分離
   - 推送規則明確（private/main vs public/open-source）
   - Vite 快速開發伺服器
   - Windows/Linux 支援（考慮 asyncio 限制）

### 4.2 用戶體驗

1. **獨特的虛擬辦公室設計**
   - Phaser 3 2D 像素遊戲引擎
   - AI 角色在辦公室移動（A* 尋路）、茶水間閒晃
   - 點擊角色開啟 AVG 風格對話框
   - 提升使用體驗的趣味性和沉浸感

2. **視覺化任務流程**
   - 拖曳式看板自動流轉（Backlog → Planning → … → Done）
   - 卡片色彩編碼、標籤分類
   - 實時運行任務在 Virtual Office 中有視覺反饋

3. **整合的儀表板**
   - 單一介面管理多個 AI、多個專案、多個排程
   - 即時系統指標（CPU/RAM/磁碟）
   - Claude 用量一目瞭然

### 4.3 業務層面

1. **成本優化**
   - 智能路由減少不必要的高成本模型調用
   - Token 消耗可見，便於預算管理
   - 支援多帳號 Round-Robin（未實現）

2. **可擴展性**
   - 新增 AI 引擎只需補充 PROVIDERS 配置
   - Member personalization 架構支援無限數量的成員
   - CronJob 系統適合大規模自動化

3. **協作友善**
   - MD 檔案 + Git 原生支援團隊協作
   - 完整的審計日誌（CardIndex.updated_at）
   - 成員工作履歷可追蹤

---

## 5. 缺點或待改進之處

### 5.1 Critical 級問題（6 個）

| # | 問題 | 影響 | 修復難度 |
|---|------|------|--------|
| **B-C1** | Gemini CLI 硬編碼絕對路徑 | 只能在特定機器上工作 | 低 |
| **B-C2** | 路徑遍歷漏洞（portrait 端點） | 安全漏洞，可讀任意檔案 | 低 |
| **B-C3** | Semaphore 替換競態條件 | 並行控制失效，超載 | 中 |
| **F-C1** | Toast 直接修改 Pinia 狀態 | 繞過封裝，可能競態 | 低 |
| **F-C2** | App.vue setInterval 未清理 | HMR 熱重載造成記憶體洩漏 | 低 |
| **F-C3** | Kanban 刪除邏輯 bug | 刪除卡片後詳情面板不關閉 | 低 |

### 5.2 Important 級問題（14 個）

**後端：**
- **B-I1** — 全表掃描找最大 ID（應用 SQL 聚合）
- **B-I2** — 檔案寫入失敗時 `_internal_writes` 未清理（內存洩漏）
- **B-I3** — Poller 先標記 running 再檢查忙碌（不必要的狀態變化）
- **B-I4** — 上傳檔案無大小限制（DoS 風險）
- **B-I5** — 任務統計全表掃描（應用 SQL GROUP BY）
- **B-I6** — 混合 naive/aware 時間戳（應統一為 UTC）
- **B-I7** — Settings 鍵無驗證（ValueError 未處理）

**前端：**
- **F-I1** — Fetch 未檢查 `res.ok`（錯誤響應直接賦值 ref，crash UI）
- **F-I2** — WebSocket 模組級單例（HMR 創建 ghost 連接）
- **F-I3** — Phaser 初始化 `setTimeout(100)` 魔法延遲
- **F-I4** — Phaser 銷毀時可能刪除系統物件
- **F-I5** — Win32 原生包在依賴中（應為 optionalDependencies）
- **F-I6** — 生產環境 console.log
- **F-I7** — 原生 confirm() 對話框（應用 ConfirmDialog 組件）

### 5.3 Minor 級問題（10 個）

- WebSocket 殭屍客戶端未斷開連接
- Windows 檔案鎖定風險
- Member slug 未生成
- 快取非線程安全
- 大量未測試的代碼
- Duplicate CSS class 定義
- Dead code：`git_safety.py` 未使用
- 類型註解不精確（`ref<any[]>`）

### 5.4 架構債務

1. **單一檔案怪物：routes.py (1395 行)**
   - 應按域拆分：projects/cards/members 子模塊
   - 缺乏 API 層測試（0 個測試）

2. **併發控制不完善**
   - Card-level locks（在 poller.py + routes.py）不一致
   - Semaphore 替換造成競態
   - busy_members 集合無 atomic 操作

3. **測試覆蓋率低**
   - Backend 路由層：0 個測試
   - 業務邏輯（runner/poller）：0 個測試
   - Frontend：0 個測試（無 Vitest/Cypress）
   - 僅有 CardData 層 ~57 個測試

4. **技術債未清**
   - `git_safety.py` 完全實現但未使用
   - `select_best_account` 邏輯實現但無人調用
   - `task_log` WebSocket 事件文檔完備但 runner 不發送
   - `gemini_usage.py` NameError（datetime import 缺失）

5. **依賴問題**
   - `python-jose` 有 CVE-2024-33663（未使用 JWT）
   - `pytest` 在生產依賴中（應為 dev-only）
   - `vuedraggable` + `@dnd-kit/vue` 重複（應移除其一）
   - Frontend dist/ committed to git（構建產物不應入版控）

6. **跨平台相容性**
   - Hardcoded Windows CLI 路徑
   - `asyncio.create_subprocess_exec` 在 Windows 下 uvicorn event loop 不支援
   - 需手動移除 `CLAUDECODE` 環境變數

---

## 6. 適用場景

### 6.1 非常適合

1. **多 AI 模型協作開發**
   - Claude 專長：coding + code review
   - Gemini：planning + architecture design
   - 自動路由選擇最合適的模型

2. **AI 驅動的自動化工程**
   - 定時代碼檢查 / 文檔生成 / 單元測試
   - Cron 排程 + 自動派遣
   - 成本可見、審計完整

3. **一人公司全棧開發**
   - OneStack 場景：1 個人 + N 個 AI 助手
   - MD 檔案 + Git 天然協作
   - 整個工作環境可遷移

4. **AI 能力研究與評估**
   - 即時觀察 AI 執行過程（log streaming）
   - Token 消耗可見
   - 支援多帳號對比測試

5. **內部開發工具 / DevOps 自動化**
   - 部署、監控告警、自動修復
   - AVG 風格介面增強團隊體驗
   - 本地優先，無需遠端依賴

### 6.2 不太適合

1. **大規模 SaaS 多租戶系統**
   - 單機 SQLite（無分佈式支持）
   - 無內置用戶認證與權限控制
   - 不適合云端部署（雖然支援 GCP）

2. **實時協作需求強的場景**
   - 單機檔案系統監視（不支援分佈式 FS）
   - Markdown 檔案無 CRDT（衝突解決手工）
   - 不適合多人同時編輯同張卡片

3. **對可靠性要求極高**
   - 無複製、無備份機制
   - local.db 單點故障
   - 無內建高可用

4. **輕量級任務管理**
   - 功能龐雜，學習曲線陡
   - 不如簡單 REST API 或 Cron job 直接

### 6.3 最佳實踐場景

**場景 A：AutoDev 自動開發系統**
```
Trello 看板 (人工輸入)
  ↓ (API import)
Aegis 卡片
  ↓ (Cron 掃描)
Poller → 自動派遣 Planning（Gemini）→ Developing（Claude）
  ↓ (log streaming)
前端 Virtual Office 監控進度
  ↓
Git commit + PR 自動生成
```

**場景 B：Greenshepherd 平台維運**
```
邊緣計算設備告警
  ↓ (HTTP POST)
Aegis 建卡
  ↓ (Cron 輪詢)
自動派遣給 Claude 分析根因
  ↓
生成維修報告 + Slack 通知
  ↓
Token 消耗記錄，成本分析
```

**場景 C：一人公司助理團隊**
```
小良哥（user） + Xiao-Jun（Claude） + Gem-ini（Gemini）
  ↓ (Virtual Office)
Xiao-Jun 編碼，Gem-ini 設計架構
  ↓ (Member Soul/Skills/Memory)
個性化工作風格，學習曲線累積
  ↓
一鍵遷移至新機器，零損失
```

---

## 7. 與競品對比

| 特性 | Aegis | Linear / Jira | GitHub Projects | Trello |
|------|-------|---------------|-----------------|--------|
| **看板** | ✓ | ✓ | ✓ | ✓✓（核心） |
| **AI 集成** | ✓✓（原生） | △（外掛） | △（GitHub Copilot） | ✗ |
| **多 AI 支持** | ✓✓（Claude/Gemini） | ✗ | ✗ | ✗ |
| **排程自動化** | ✓（Cron） | △（Workflow） | △（Actions） | ✗ |
| **即時日誌** | ✓✓（WebSocket） | △（webhook） | △（logs） | ✗ |
| **本地優先** | ✓✓（SQLite） | ✗ | ✗ | ✗ |
| **MD 驅動** | ✓✓ | △ | △ | ✗ |
| **虛擬辦公室** | ✓✓（獨有） | ✗ | ✗ | ✗ |
| **成本追蹤** | ✓✓（AI Token） | ✗ | △（使用量） | ✗ |
| **擴展性** | ↓（單機） | ↑（企業級） | ↑ | ↑ |
| **學習曲線** | ↑ | ↑ | ↑ | ↓ |

---

## 8. 建議與優先級

### 優先級 1（Critical，本月）

1. **修復 Gemini 路徑硬編碼**（B-C1）
   - 改為 `["gemini"]` + PATH 檢測
   - 支援跨平台

2. **路徑遍歷安全修復**（B-C2）
   - 驗證 filename 相對性
   - 預防任意檔案讀取

3. **Semaphore 替換競態**（B-C3）
   - 改用 `release()` + `_value` 調整（已有註解）
   - 寫 unit test 驗證

### 優先級 2（Important，3 個月）

1. **增加 API 層測試**
   - routes.py 至少覆蓋核心端點
   - 使用 pytest + httpx
   - 目標：80%+ 覆蓋

2. **拆分 routes.py**
   - 按域建子模塊：projects, cards, members
   - 每模塊 <500 行

3. **完善錯誤處理**
   - Fetch 檢查 `res.ok`
   - Settings 驗證 allowlist
   - 檔案大小限制

4. **時間戳統一**
   - 全改為 `datetime.now(timezone.utc)`
   - 移除 naive datetimes

### 優先級 3（Nice to have，6 個月）

1. **分佈式支持**
   - 遷移 PostgreSQL（保留 SQLite 本地開發）
   - 引入 Redis 快取
   - 支援橫向擴展

2. **認證與多租戶**
   - OAuth 用戶認證
   - 組織/項目級隔離
   - RBAC 權限模型

3. **消除 Dead Code**
   - 啟用 `git_safety.py`
   - 實現 `task_log` WebSocket 事件
   - 整理 `gemini_usage.py`

4. **前端測試**
   - Vitest + @vue/test-utils
   - 至少覆蓋 Kanban、Office 核心邏輯
   - 目標：50%+ 覆蓋

---

## 9. 總結

### 核心特色

Aegis 是一個 **AI-first 的任務管理與調度平台**，獨特之處在於：

1. **原生多 AI 支持** — 不只是 API 調用，而是完整的角色上下文注入
2. **MD 檔案驅動** — Git 友善、人機可讀、易於團隊協作
3. **實時沉浸式體驗** — Pixel art 虛擬辦公室 + AVG 對話框
4. **完整成本追蹤** — Token 消耗可見，便於預算管理
5. **本地優先設計** — SQLite + 整個資料夾可遷移，無雲鎖定

### 適用對象

- **AI 開發團隊**（多模型協作）
- **自動化工程師**（Cron + 智能派遣）
- **一人公司**（AI 助手團隊）
- **研究人員**（評估 AI 能力成本）

### 當前狀態

- **功能完整度**：7/10（核心功能都有，邊界情況欠缺）
- **代碼品質**：5/10（無測試、架構債務、並發控制缺陷）
- **生產就緒度**：4/10（需修複 6 個 Critical bug 才能上線）

### 下一步

優先修複 6 個 Critical 問題（~1 周），補充 API 層測試（~4 周），即可達到 MVP+ 品質。

---

**報告完成日期**：2026-03-09
**數據來源**：Aegis GitHub 倉庫（G:\Yooliang\Aegis）
