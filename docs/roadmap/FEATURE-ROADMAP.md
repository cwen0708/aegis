# Aegis 功能開發清單

> 基於 14 個 AI Agent 專案的優點整合
> 生成日期：2026-03-09 ｜ 更新：2026-03-13

---

## 現狀評估

### Aegis 已有的優勢
- ✅ 虛擬辦公室（獨有）
- ✅ MD 檔案驅動 + Git 原生
- ✅ 多 AI 路由（Claude/Gemini）+ 帳號 Fallback
- ✅ Cron 排程
- ✅ 成本追蹤（Claude Token）
- ✅ WebSocket 即時監控
- ✅ Member 人設/技能/記憶
- ✅ 成員收件匣（跨 Agent 通訊基礎）
- ✅ CI/CD 自動部署 + 熱更新 API

### Aegis 缺少的常見功能
| 功能 | 其他專案表現 | Aegis 現狀 |
|------|-------------|-----------|
| 多頻道通訊 | Nanobot(9)、ZeroClaw(15+)、PicoClaw(12+) | ❌ 無 |
| 更多 LLM | ZeroClaw(20+)、ClawRouter(41+) | △ 僅 2 個 |
| 智能路由 | ClawRouter(81%省)、Spacebot(四層) | △ 帳號 fallback 已完成 |
| 容器隔離 | IronClaw(WASM+Docker)、NanoClaw | ❌ 無 |
| 安全機制 | IronClaw(注入防禦)、Spacebot | ❌ 有漏洞 |
| 向量搜索 | IronClaw(pgvector)、Spacebot(LanceDB) | ❌ 無 |
| 技能市集 | ClawHub、IronClaw(MCP) | △ 本地 Skills |
| CLI 工具 | IronClaw、ZeroClaw、Nanobot | ❌ 無 |
| 瀏覽器自動化 | CoPaw(Playwright)、Spacebot | ❌ 無 |

---

## 開發優先級

### ~~P0: 緊急修復~~ ✅ 完成（2026-03-09 ~ 03-10）

> 來自 ANALYSIS.md 的 6 個 Critical Bug

| # | 任務 | 來源 | 狀態 |
|---|------|------|:----:|
| 1 | 修復 Gemini CLI 硬編碼路徑 | B-C1 | ✅ |
| 2 | 修復路徑遍歷安全漏洞 | B-C2 | ✅ |
| 3 | 修復 Semaphore 競態條件 | B-C3 | ✅ |
| 4 | 修復 Toast 直接修改 Pinia | F-C1 | ✅ |
| 5 | 修復 App.vue setInterval 未清理 | F-C2 | ✅ |
| 6 | 修復 Kanban 刪除邏輯 bug | F-C3 | ✅ |

---

### P1: 多頻道通訊（2-3 週）

> 參考：Nanobot、PicoClaw、ZeroClaw

**目標**：讓用戶通過 Telegram/LINE/Discord 建卡、查詢、中止任務

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | Telegram Bot 整合 | Nanobot、zclaw | 3d |
| 2 | LINE Bot 整合 | HappyNAS | 2d |
| 3 | Discord Bot 整合 | Spacebot、PicoClaw | 2d |
| 4 | 統一頻道管理器 | Nanobot ChannelManager | 2d |
| 5 | 遠端建卡 API | - | 1d |
| 6 | 任務狀態查詢 API | - | 1d |
| 7 | 任務中止 API | - | 1d |

**技術選型**：
- Telegram: `python-telegram-bot`
- LINE: `line-bot-sdk`
- Discord: `discord.py`
- 架構：類似 CoPaw 的 ChannelManager 統一接入

---

### P2: 擴展 LLM 支援（1-2 週）

> 參考：ZeroClaw (20+)、ClawRouter (41+)、Nanobot (23+)

**目標**：支援更多 LLM 提供商，降低成本、增加選擇

| # | LLM | 優先級 | 預估 | 說明 |
|---|-----|-------|------|------|
| 1 | OpenAI (GPT-4o) | 高 | 1d | 通用能力 |
| 2 | DeepSeek | 高 | 1d | 性價比高 |
| 3 | Ollama (本地) | 高 | 2d | 離線能力 |
| 4 | OpenRouter | 中 | 1d | 統一接入多模型 |
| 5 | 智谱 AI (GLM) | 低 | 1d | 中國市場 |
| 6 | 通義千問 | 低 | 1d | 中國市場 |

**架構改動**：
```python
# backend/app/providers/
├── base.py       # LLMProvider 抽象類
├── claude.py     # Claude CLI
├── gemini.py     # Gemini CLI
├── openai.py     # OpenAI API
├── deepseek.py   # DeepSeek API
├── ollama.py     # Ollama 本地
└── factory.py    # 工廠方法
```

---

### P3: 智能路由增強（1-2 週）

> 參考：ClawRouter (81% 成本節省)、Spacebot (四層路由)

**目標**：根據任務複雜度自動選擇最佳模型，降低成本

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | 任務複雜度評估器 | ClawRouter | 2d |
| 2 | 成本/性能路由表 | ClawRouter | 1d |
| 3 | 備援鏈（失敗自動切換） | Spacebot | ✅ 帳號 fallback |
| 4 | 路由統計與優化建議 | ClawRouter | 2d |

**路由策略**：
```
任務類型        → 推薦模型        → 備援
──────────────────────────────────────
簡單查詢        → DeepSeek        → GPT-4o-mini
代碼生成        → Claude          → GPT-4o
架構設計        → Gemini          → Claude
代碼審查        → Claude          → DeepSeek
文檔生成        → GPT-4o-mini     → DeepSeek
```

---

### P4: 安全機制強化（1-2 週）

> 參考：IronClaw、NanoClaw、ZeroClaw

**目標**：防止惡意輸入、保護敏感資料

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | 提示注入防禦 | IronClaw SafetyLayer | 2d |
| 2 | 敏感資料洩漏檢測 | IronClaw LeakDetector | 2d |
| 3 | 工具輸出清洗 | Spacebot | 1d |
| 4 | 環境變數消毒 | Spacebot | 1d |
| 5 | API 速率限制 | ZeroClaw | 1d |
| 6 | 上傳檔案大小限制 | - | 0.5d |

**實現參考**：
```python
# backend/app/safety/
├── sanitizer.py    # 模式檢測、內容轉義
├── validator.py    # 輸入驗證
├── leak_detector.py # 敏感資料掃描
└── policy.py       # 安全策略規則
```

---

### P5: 向量搜索記憶（2-3 週）

> 參考：IronClaw (pgvector+RRF)、Spacebot (LanceDB+RRF)、CoPaw (ReMe)

**目標**：讓 AI 能語義搜索歷史任務、代碼、文檔

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | 嵌入向量生成 | IronClaw OpenAI Embedding | 2d |
| 2 | 向量存儲後端 | LanceDB (輕量) 或 Qdrant | 3d |
| 3 | 混合搜索 (FTS + Vector + RRF) | IronClaw/Spacebot | 3d |
| 4 | 記憶自動壓縮 | CoPaw ReMe | 2d |
| 5 | 記憶 API 暴露給 AI | IronClaw memory_search | 1d |

**架構**：
```
卡片/代碼/文檔 → Embedding → LanceDB
                            ↓
AI 任務 → memory_search → 混合搜索 (RRF) → 相關上下文
```

---

### P6: 容器隔離執行（2-3 週）

> 參考：IronClaw (Docker)、NanoClaw (Apple Container)、ZeroClaw (多層沙箱)

**目標**：AI 執行任務時在隔離環境中，防止惡意代碼

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | Docker 容器執行模式 | IronClaw sandbox | 3d |
| 2 | 網路白名單代理 | IronClaw NetworkProxy | 2d |
| 3 | 憑證注入機制 | IronClaw CredentialInjector | 2d |
| 4 | 資源限制 (CPU/RAM/時間) | ZeroClaw | 1d |
| 5 | 可選：WASM 沙箱 (輕量任務) | IronClaw wasmtime | 5d |

---

### P7: CLI 工具（1 週）

> 參考：IronClaw、ZeroClaw、Nanobot

**目標**：命令行管理 Aegis，無需開瀏覽器

| # | 命令 | 說明 | 預估 |
|---|------|------|------|
| 1 | `aegis init` | 初始化專案 | 0.5d |
| 2 | `aegis card create` | 建立卡片 | 0.5d |
| 3 | `aegis card list` | 列出卡片 | 0.5d |
| 4 | `aegis run <card_id>` | 手動執行任務 | 0.5d |
| 5 | `aegis status` | 系統狀態 | 0.5d |
| 6 | `aegis logs <card_id>` | 查看日誌 | 0.5d |
| 7 | `aegis cron list/add/rm` | 排程管理 | 1d |

**技術選型**：`typer` (Python) 或 `cobra` (如果考慮 Go 重寫)

---

### P8: 技能/插件系統增強（2 週）

> 參考：ClawHub、IronClaw (Skills+MCP)、Nanobot

**目標**：讓用戶能安裝/分享技能包

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | Skills 格式標準化 (SKILL.md) | IronClaw | 2d |
| 2 | Skills 本地註冊表 | IronClaw SkillRegistry | 2d |
| 3 | Skills 啟用/停用 UI | IronClaw | 1d |
| 4 | MCP 協議支援 | IronClaw/Nanobot | 3d |
| 5 | Skills 分享/導入功能 | ClawHub | 2d |

---

### P9: 瀏覽器自動化（1-2 週）

> 參考：CoPaw (Playwright)、Spacebot (chromiumoxide)

**目標**：AI 能操作網頁、截圖、填表

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | Playwright 整合 | CoPaw | 2d |
| 2 | 網頁截圖工具 | CoPaw | 1d |
| 3 | 元素定位工具 | Spacebot (ref 系統) | 2d |
| 4 | 表單填寫工具 | - | 2d |
| 5 | 無頭瀏覽器管理 | - | 1d |

---

### P10: 多代理協作增強（2-3 週）

> 參考：Spacebot (委派模型)、TinyClaw (團隊協作)

**目標**：讓多個 AI 成員能互相溝通、分工合作

| # | 任務 | 參考專案 | 預估 |
|---|------|---------|------|
| 1 | Agent 間訊息傳遞 | TinyClaw [@agent: msg] | ✅ 成員收件匣 |
| 2 | 任務分解與分派 | Spacebot Branch/Worker | 3d |
| 3 | 結果聚合機制 | Spacebot Compactor | 2d |
| 4 | 協作可視化 | Aegis Virtual Office | 2d |
| 5 | 並行任務協調 | Spacebot | 2d |

---

## 開發路線圖

```
2026 Q1 (3月)
├── Week 1-2: P0 緊急修復 ✅ + 虛擬辦公室/排程/部署 ✅
├── Week 2-3: 成員收件匣 + AI 帳號 Fallback + 對話框優化 ✅
├── Week 3-4: P1 多頻道通訊 (Telegram/LINE)
└── Week 5-6: P2 擴展 LLM (OpenAI/DeepSeek/Ollama)

2026 Q2 (4-6月)
├── Month 1: P3 智能路由 + P4 安全機制
├── Month 2: P5 向量搜索記憶
└── Month 3: P6 容器隔離

2026 Q3 (7-9月)
├── Month 1: P7 CLI 工具 + P8 技能系統
├── Month 2: P9 瀏覽器自動化
└── Month 3: P10 多代理協作
```

---

## 功能對比目標

完成所有開發後，Aegis 與其他專案對比：

| 功能 | Aegis (現) | Aegis (目標) | IronClaw | Spacebot | Nanobot |
|------|:----------:|:------------:|:--------:|:--------:|:-------:|
| 多 LLM | △ (2) | ✓ (6+) | ✓ (6+) | ✓ | ✓ (23+) |
| 多頻道 | ❌ | ✓ (3+) | ✓ (5+) | ✓ (5) | ✓ (9) |
| 智能路由 | △ (fallback) | ✓✓ | ✓ | ✓✓ | - |
| 容器隔離 | ❌ | ✓ | ✓✓ | ✓ | - |
| 安全機制 | ❌ | ✓✓ | ✓✓✓ | ✓✓ | △ |
| 向量搜索 | ❌ | ✓✓ | ✓✓ | ✓✓ | - |
| CLI 工具 | ❌ | ✓ | ✓✓ | ✓ | ✓ |
| 技能系統 | △ | ✓✓ | ✓✓ | ✓ | ✓ |
| 虛擬辦公室 | ✓✓ | ✓✓ | - | - | - |
| 成本追蹤 | ✓ | ✓✓ | - | - | - |
| 多代理協作 | △ (收件匣) | ✓✓ | △ | ✓✓ | - |

---

## 快速實現建議

### 最大 ROI（投入/回報比）

1. **P1 多頻道通訊** — 直接復用 HappyNAS 的 LINE/Telegram Bot 經驗
2. **P2 OpenRouter 整合** — 一個 API 接入 41+ 模型
3. **P4 安全機制** — 可直接參考 IronClaw 的 SafetyLayer 設計

### 可選跳過

- P9 瀏覽器自動化 — 如果不需要爬蟲/網頁操作場景
- P6 容器隔離 — 如果只在可信環境運行

### 整合建議

| 現有系統 | 整合方式 | 狀態 |
|---------|---------|:----:|
| HappyNAS | 復用 LINE/Telegram Bot 代碼 | 待開發 |
| AutoDev | Aegis 作為 AutoDev 的 Web UI | ✅ 運作中 |
| Trello | 保留現有 Trello 整合，Aegis 作為執行層 | ✅ 運作中 |
| OneStack | 雙向同步（Phase 1-3） | △ 規劃中 |

---

*本清單基於 14 個 AI Agent 專案分析，結合 Aegis 現狀生成。*
*生成日期：2026-03-09 ｜ 更新：2026-03-13*
