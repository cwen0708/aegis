# Aegis — AI Agent Management Dashboard

**Aegis（神盾）** 是一個開源的 AI 代理管理平台，讓你像管理真人團隊一樣管理 AI 代理。支援 Claude、Gemini 等多種 AI 引擎，提供看板任務管理、排程自動化、即時串流監控、多頻道通訊、以及 AI 自我進化開發等功能。

![Virtual Office](docs/screenshots/office.png)

## Why Aegis?

大多數 AI 工具是「你問一次、它答一次」的對話模式。Aegis 不同 — 它把 AI 當作團隊成員來管理：

- **分配任務**：把工作卡片指派給 AI，它會自動完成
- **排程執行**：設定 cron 排程，AI 定時巡檢、分析、生成報告
- **即時監控**：任務執行中可以看到 AI 正在讀什麼檔案、跑什麼指令
- **多帳號 Fallback**：主帳號額度滿了自動切備用帳號
- **跨頻道互動**：從 Telegram 直接跟 AI 成員對話、傳圖片、接收報告

## Features

### AI 任務管理
- **看板式任務流** — 拖曳卡片在 Backlog → Planning → Developing → Done 間流轉，AI 自動接手執行
- **三層路由** — 列表指派 → 專案預設 → 全域 fallback，靈活決定哪個 AI 處理哪張卡片
- **帳號 Fallback** — 主帳號失敗時自動切換備用帳號，任務不中斷
- **PTY 即時串流** — 任務執行中可即時看到 AI 的每一步操作（讀檔、跑指令、寫程式）
- **自動重試** — 首次失敗自動排入下一輪重試，減少人工介入

### 排程自動化
- **Cron 排程引擎** — 標準 cron expression，定時觸發 AI 任務
- **排程日誌** — 每次執行記錄完整的輸入/輸出/耗時/費用
- **階段動作** — 任務完成後可自動封存、移動到指定列表、或刪除

### AI 團隊
- **虛擬辦公室** — 像素風辦公場景，AI 角色在工作台工作，A* 尋路動畫
- **角色個性** — 每個 AI 成員有獨立的靈魂設定、技能檔案、記憶系統
- **AVG 對話** — 點擊角色開啟日系動漫風格對話框，顯示任務總結
- **AI 立繪生成** — 上傳真人照片，Gemini 分析特徵後生成動漫風立繪

![Character Dialog](docs/screenshots/character-dialog.png)

### 多頻道通訊
- **Telegram Bot** — 從手機跟 AI 成員即時對話
- **多模態支援** — 傳送圖片讓 AI 分析、接收 AI 生成的圖表和報告
- **Gemini 圖片生成** — AI 可呼叫 Gemini 生成視覺化圖表、示意圖
- **Email 處理** — AI 自動分類郵件、摘要、建議處理動作

### MCP 工具整合
- **標準 MCP 協議** — 支援 Model Context Protocol，AI 可呼叫外部工具
- **成員級 MCP 設定** — 每個 AI 成員可配置不同的 MCP 伺服器
- **自動注入** — 任務執行時自動載入成員的 `.mcp.json`，無需手動配置
- **可擴展** — 自訂 MCP 伺服器連接任意資料來源（資料庫、檔案系統、API 等）

### 安全與隔離
- **環境變數白名單** — AI subprocess 只能存取允許的環境變數，敏感資訊不洩漏
- **Process Group 隔離** — AI 任務在獨立 process group 執行，不影響主服務
- **CLAUDE.md 安全指令** — 限制 AI 只能操作專案目錄，禁止危險命令
- **專案密鑰管理** — 環境變數透過 DB 管理，不寫在檔案中

### 監控與管理
- **服務儀表板** — Worker/Runner 狀態、PID、系統資源（CPU/RAM/Disk）即時監控
- **任務日誌** — Token 用量、費用、耗時、模型分類完整記錄
- **熱更新** — Git tag 觸發自動部署，不停機更新
- **Web Terminal** — 瀏覽器內直接操作伺服器終端機
- **Claude Remote Control** — 從專案頁面一鍵啟動 Claude RC，手機遠端操控

### 協作
- **跨成員協作** — AI 成員可以互相建立卡片、請求協助
- **協作回饋** — 協助完成後自動通知原始請求者，寫入記憶
- **頻道通知** — 任務完成/失敗自動推送到綁定的 Telegram 群組

![Kanban Board](docs/screenshots/kanban.png)

## Quick Start

### One-line Install

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/cwen0708/aegis/main/scripts/install-windows.ps1 | iex
```

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/cwen0708/aegis/main/scripts/install-linux.sh | bash
```

安裝完成後開啟 http://localhost:8899

### Manual Setup

**Prerequisites:** Python 3.10+, Node.js 18+, Claude Code CLI 或 Gemini CLI

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8899

# Frontend
cd frontend
npm install
npm run dev
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3 + TypeScript + Vite + Tailwind CSS 4 |
| Backend | Python 3.12 + FastAPI + SQLModel |
| Database | SQLite (local-first, portable) |
| Real-time | WebSocket (native FastAPI) |
| AI Engines | Claude Code CLI, Gemini CLI, Ollama |
| Task Worker | PTY streaming + account fallback |
| Channels | Telegram, LINE, Discord, Email (IMAP) |
| MCP | Model Context Protocol (extensible) |

## Architecture

```
                    ┌─ Telegram ─┐
                    ├─ LINE      ├──→ Channel Router ──→ Chat Handler ──→ Runner
                    └─ Email     ┘                                        (Claude/Gemini CLI)

Browser ──→ Vue 3 SPA ←──WebSocket──→ FastAPI
                                        ├─ REST API
                                        ├─ Cron Poller (排程)
                                        └─ Card Watcher (檔案監控)

Worker (獨立程序) ──→ 掃描 pending 卡片 ──→ PTY 執行 ──→ 即時串流 ──→ WebSocket 廣播
                      ├─ 三層路由
                      ├─ 帳號 Fallback
                      ├─ Workspace 隔離
                      └─ MCP 工具注入
```

## Documentation

- [Directory Structure](DIRECTORY.md) — `.aegis/` 完整目錄結構、chat_key 命名規則、會議系統架構
- [Runner vs Worker](docs/runner-vs-worker.md) — 兩條 AI 執行路徑的比較與 Executor 模組
- [Process Pool](docs/process-pool.md) — ProcessPool 持久進程架構
- [API Endpoints](docs/api.md)
- [WebSocket Events](docs/websocket.md)

## License

MIT License — see [LICENSE](LICENSE) for details.
