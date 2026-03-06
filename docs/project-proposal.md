# 專案提案：Aegis (AI Engineering Grid & Intelligence System)

## 1. 專案願景與定位

**Aegis (神盾 / 庇護所)** 是一個全新設計的「AI 開發團隊調度與卡片管理中心」。

它將取代目前分散的 `AutoDev` (依賴 Trello) 與 `Claude-PM` (依賴檔案/Supabase)，成為一個統一的、具備視覺化介面的專案管理系統。它不僅讓人類 (小良哥) 能直觀地管理跨專案進度，更是專為「多重 AI 代理 (Gemini, Claude, Deepseek 等)」設計的原生工作平台。

### 為什麼叫 Aegis？
代表著堅固、防護與智能調度。它是管理 AI 團隊的堅實後盾，確保 AI 在受控、安全的環境下高效率產出。

*(備選名稱：Nexus, Nexus-Dev, AITrack, Orchestrator)*

---

## 2. 核心架構：統一的工作流模型

捨棄外部 Trello，建立我們自己的卡片系統。這能徹底解決 Trello API 限制、標籤管理困難等問題，並且深度整合 Git 與本地檔案系統。

### 2.1 層級結構

1. **跨專案調度中心 (Global Dashboard)**
   - 鳥瞰所有專案的進度、資源分配與 AI Token 用量。
   - 負責決定哪個專案的卡片優先級最高，進行跨專案的任務派發。
2. **專案 (Project)**
   - 對應到實體磁碟的代碼庫 (如 `G:\cwen0708\infinite-novel`)。
   - 包含該專案專屬的配置 (Deploy Type, 預設使用的 AI 引擎)。
3. **卡片列表 (List / Stage)**
   - 例如：Backlog, Planning, Developing, Verifying, Done, Aborted。
4. **卡片 (Card / Task)**
   - 任務的最小單位。
   - **核心驅動力：Tag (標籤)**。所有的路由、派發、狀態流轉完全依賴 Tag（例如：`[AI-Gemini]`, `[Needs-Review]`, `[P0]`, `[Bug]`）。

### 2.2 系統組件

- **前端介面 (UI)**：Vue 3 + TailwindCSS (或自定義 CSS)。提供類似 Trello 的看板 (Kanban) 視圖，支援拖曳。
- **後端引擎 (Backend)**：FastAPI (Python) 或 Node.js (Express)。
- **資料儲存 (Database)**：**全本地化 SQLite (`local.db`)**。這是本系統「極致可攜性」的關鍵。採用 Local-First 架構，整個系統的卡片資料、歷史紀錄與狀態都儲存在一個實體檔案中。您可以將整個 Aegis 資料夾打包，丟到任何環境 (DGX, GCP, 筆電) 中一鍵還原並無縫啟動，完全不需要依賴外部網路資料庫。
- **AI 執行器 (Agent Runner)**：繼承並強化我們剛才寫的 `run-ai` 路由邏輯，支援多引擎切換。

### 2.3 任務觸發與佇列管理 (Task Trigger & Queue)

為了解決舊有系統中「實時觸發 (Claude-PM)」與「定時輪詢 (AutoDev)」不一致的問題，Aegis 將實作一個**統一的非同步任務佇列 (Unified Task Queue)**，並導入先進的 AI 心跳機制：

- **混合觸發器 (Hybrid Triggers)**：
  1. **實時觸發 (Event-Driven)**：支援 Webhook 或 API 呼叫。當外部系統 (如 Supabase) 或使用者透過 Telegram 建立緊急卡片並打上 `[P0]` 標籤時，立即將任務推入佇列。
  2. **AI 心跳機制 (Heartbeat & Triage Agent)**：這是本系統最核心的智能中樞。借鑑 OpenClaw 的設計，系統每 30 分鐘會執行一次「心跳」。
     - **運作方式**：系統收集過去 30 分鐘的「世界狀態」（包含未分類的 Telegram 訊息、系統警報、未處理的原始數據），並交給一個**低成本/高速度的 AI 模型**（如 Gemini 2.0 Flash 或 DGX 本地模型）進行檢視。
     - **分流決策**：這個 Triage Agent (分流總機) 負責判斷現狀。如果沒事，它選擇「休眠」以節省資源；如果有事，它會自動將這些非結構化資訊轉化為標準的「任務卡片」，打上對應的 Tag（如 `[AI-Coding]`, `[Ops]`），並推入佇列。
- **優先級調度 (Priority Scheduler)**：進入佇列的任務根據卡片的 Tag (如 `P0`, `P1`) 進行排序。即使是定時任務抓取到的一般工作，也會禮讓給突發的實時高優先級任務。

---

## 3. 殺手級功能：原生 AI 整合

Aegis 與一般專案管理工具（如 Jira, Trello）最大的不同，在於它具備「自我改善的檔案與 Git 機制」。

### 3.1 Tag 驅動的智能派發
使用者只需建立卡片並貼上標籤：
- 貼上 `[AI-Planning]`：系統自動喚醒 **Gemini** 閱讀專案，產出 `plan.md`，並將狀態改為 `[AI-Ready]`。
- 貼上 `[AI-Coding]`：系統自動喚醒 **Claude** 根據計畫書修改代碼，完成後自動執行 `git commit`，並進入 `[Verifying]`。

### 3.2 深度 Git 與檔案系統整合 (Claude-PM 的優勢)
- **程式碼關聯**：卡片直接與本地路徑 (`G:\...`) 綁定。
- **自動回滾 (Rollback)**：當 AI 測試失敗或 `max_retries` 時，Aegis 能夠自動執行 `git reset --hard` 並將卡片標籤改為 `[AI-Aborted]`。
- **檔案級別的 Prompting**：卡片描述直接作為 Markdown 檔案餵給 CLI，沒有中間轉換的損耗。

### 3.3 資源與用量監控
- 內建 `Usage PM` 儀表板，整合 `OpenClaw` 的邏輯，統計每個專案、每個 AI 引擎的 Token 消耗與成本。

---

## 4. 實作計畫 (Roadmap) 與細節展開

這是一個中大型專案，建議分階段實行，以確保現有營運不中斷。以下是各階段的詳細技術規劃：

### Phase 1: 核心後端與資料庫建立 (約 1-2 天)
**目標**：建立脫離 Trello 的本地資料庫基礎，並提供 API 供未來的前端和 AI 執行器使用。
- **技術棧**：Python (FastAPI) + SQLite + SQLAlchemy/SQLModel + Passlib (JWT 驗證)。
- **身分管理機制 (Auth)**：實作輕量級的 JWT 登入系統。因為是自用與團隊內部工具，初期僅需單一 Admin 帳號或設定白名單邀請機制，保護 API Endpoint 與前端看板不被外網未授權存取。
- **資料庫架構 (Schema 草案)**：
  - `users`: `id`, `username`, `password_hash`, `role`。
  - `projects`: `id`, `name`, `path` (實體路徑), `deploy_type`, `default_provider`。
  - `lists`: `id`, `project_id`, `name` (如 Backlog, Planning, Done), `position`。
  - `cards`: `id`, `list_id`, `title`, `description`, `content` (存放 Markdown 內容), `status`, `created_at`, `updated_at`。
  - `tags`: `id`, `name` (如 `AI-Gemini`, `P0`), `color`。
  - `card_tags`: 關聯表。
  - `comments`: 紀錄 AI 執行日誌或人類留言。
- **任務**：
  1. 初始化 FastAPI 專案結構並設定 JWT 中介軟體 (Middleware)。
  2. 建立 SQLite 資料庫與 ORM 模型。
  3. 實作基礎 CRUD API (Create, Read, Update, Delete) 用於專案與卡片。

### Phase 2: AI 路由、資源管理與 Git 整合 (約 1-2 天)
**目標**：將目前的 `AutoDev` 腳本與 `Claude-PM` 的執行器融合，升級為具備資源保護機制的背景執行緒 (Daemon)。
- **技術棧**：Python `asyncio`, `subprocess`, `GitPython`, `psutil` (硬體監控)。
- **任務**：
  1. **Agent Runner (並行控制)**：繼承 `Claude-PM` 的 `max_concurrent` 槽位 (Slot) 機制。利用 `asyncio.Semaphore` 限制同時執行的 AI 進程數量（預設 3 個），避免 DGX 或 GCP 伺服器因為同時啟動多個 Node/Python 環境而導致 OOM (Out of Memory)。
  2. **硬體資源監控**：整合 `psutil` 收集 CPU 使用率、記憶體佔用與系統負載，即時寫入資料庫，供前端儀表板顯示。當 CPU/RAM 超過危險閾值（如 90%）時，Agent Runner 應暫停分配新任務。
  3. **動態路由模組**：當卡片被打上特定 Tag 時，Runner 從佇列中取得任務，根據 `PHASE_ROUTING` 決定喚醒 Gemini 或 Claude CLI 進入空閒槽位執行。
  4. **Git Safety 模組**：在 AI 執行前自動 `git stash` 或建立新分支。如果 AI 執行失敗，自動執行 `git reset --hard` 回滾，並在卡片中寫入錯誤日誌，最後打上 `[Aborted]` 標籤。

### Phase 3: 前端看板與管理中心開發 (約 2-3 天)
**目標**：提供一個直觀、可拖曳的 Kanban 介面，並具備完整的 AI 團隊與系統管理功能，徹底取代 Trello 與命令列操作。
- **技術棧**：Vue 3 (Composition API) + Vite + TailwindCSS + `vuedraggable` + `xterm.js` (終端機顯示)。
- **核心介面設計**：
  1. **Global Dashboard (調度與用量中心)**：
     - 顯示活躍卡片數、AI 槽位狀態與即時硬體資源 (CPU/RAM)。
     - **用量與成本分析 (Cost Analytics)**：視覺化呈現各 AI 引擎 (Gemini/Claude) 及各專案的 Token 消耗量與估算成本。
  2. **Project Kanban (專案看板)**：
     - 經典的 Trello 視圖，支援列表與卡片雙向拖曳。
     - 混合顯示「單次開發任務」與「Cron 定時營運任務」。
  3. **Card Modal & Execution Console (卡片與執行終端)**：
     - 左側：Markdown 編輯器編寫任務內容，並支援 Tag 管理。
     - 右側：**即時執行終端機 (Interactive Console)**。當 AI 執行任務時，即時串流 (Stream) 顯示 stdout/stderr 日誌。提供「強制中斷 (Abort)」與「人工介入回覆」的按鈕。
  4. **Settings & Prompt Library (系統與提示詞設定)**：
     - **專案配置**：管理專案實體路徑與機密環境變數 (Secrets 注入)。
     - **共用提示詞庫 (Prompt Library)**：內建 Markdown 編輯器，可直接在網頁上維護 `plan.md`, `develop.md` 及核心指令，統一管理 AI 團隊的「靈魂」。

### Phase 4: 多頻道通訊介面整合 (Omni-Channel Integration)
**目標**：將 Aegis 的監控、通知與快速建卡功能延伸到多種通訊平台上。借鑑 OpenClaw 的 `Channels` 架構，實作一個抽象的通訊介面。
- **技術棧**：Python `FastAPI` (Webhook 接收), `httpx` (API 呼叫)。
- **抽象層設計 (Channel Adapter)**：
  - 建立一個通用的 `BaseChannel` 類別，定義 `send_message()`, `receive_message()`, `register_webhook()` 等標準方法。
  - 將傳入的訊息標準化為統一的 `AegisMessage` 格式，再交由 Triage Agent (心跳機制) 處理。
- **首波實作 (Telegram 作為示範)**：
  1. **主動通知 (Push Notifications)**：當 AI 完成高優先級卡片 (如 `P0`)，或發生 `max_retries` / 資源超載時，透過 Channel Adapter 主動推播訊息至指定的聊天室。
  2. **指令操作 (Slash Commands)**：
     - `/status`：查看目前正在執行的 AI 任務與伺服器資源狀況 (CPU/RAM)。
     - `/abort <card_id>`：遠端中止卡在死迴圈的卡片。
  3. **快速建卡 (Quick Add)**：直接在聊天室傳送文字訊息，機器人會自動將其解析並建立成一張預設放在 `Backlog` 列表的新卡片。
- **跨系統協同 (與 OneStack 整合)**：
  - **作為 OneStack 的資料收集器**：利用這個 Omni-Channel 架構，Aegis 可以成為 OneStack (商業營運系統) 的「外部聽診器」。例如，您可以寫一個 `OneStackChannel`，當 Aegis 在 Telegram 或 LINE 上收到客戶的回饋或 Bug 回報時，Triage Agent 判斷後，可以透過 API 將其自動轉發至 OneStack 的 `Capture Stack (需求擷取)` 模組中。
- **未來擴展性**：由於採用了抽象的 Channel 架構，未來只要實作新的 Adapter (如 `SlackChannel`, `LineChannel`, `DiscordChannel`)，只需修改設定檔，就能讓 Aegis 團隊在多個平台上同時為您服務。

### Phase 5: 遷移與上線 (約 1 天)
**目標**：無縫接軌，停用舊系統。
- **任務**：
  1. **資料匯入腳本**：撰寫一個一次性的 Python 腳本，透過 Trello API 讀取現有 `AutoDev` 看板的未完成卡片，寫入到本地的 SQLite `local.db` 中。
  2. **整合 Claude-PM**：將 `Claude-PM` 中基於檔案監控的 `om-ai` 與 `policy-ai` 任務，改寫為直接透過 API 在 Aegis 中建立卡片。
  3. **部署**：將 Aegis 打包，配置 PM2 或 systemd 在背景運行 FastAPI 與前端靜態檔案伺服器。關閉原有的 Windows 工作排程器 (`run-auto-dev.ps1`)。

---

## 5. 結論

建立 **Aegis** 是我們 AI 開發流程的「奇異點」。它將讓我們擺脫外部工具的限制，獲得一個完全為 AI 量身打造、高度自動化且資源受控的專屬開發宇宙。
