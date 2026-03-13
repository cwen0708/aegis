# Aegis 功能開發清單摘要

> 基於 14 個 AI Agent 專案優點整合
> 初版：2026-03-09 ｜ 更新：2026-03-13

---

## 現狀 vs 目標

| 功能 | 現狀 | 目標 | 參考專案 |
|------|:----:|:----:|----------|
| 多頻道通訊 | △ | ✓ (3+) | Nanobot, PicoClaw, ZeroClaw |
| 多 LLM 支援 | △ (2) | ✓ (6+) | ZeroClaw, ClawRouter |
| 智能路由 | △ (fallback) | ✓✓ | ClawRouter, Spacebot |
| 容器隔離 | ❌ | ✓ | IronClaw, NanoClaw |
| 安全機制 | ❌ | ✓✓ | IronClaw, Spacebot |
| 向量搜索 | ❌ | ✓✓ | IronClaw, Spacebot |
| CLI 工具 | ❌ | ✓ | Nanobot, ZeroClaw |
| 技能系統 | △ | ✓✓ | ClawHub, IronClaw |
| 瀏覽器自動化 | ❌ | ✓ | CoPaw, Spacebot |
| 多代理協作 | △ (收件匣) | ✓✓ | Spacebot, TinyClaw |
| 虛擬辦公室 | ✓✓ | ✓✓ | 獨有優勢 |
| 成本追蹤 | ✓ | ✓✓ | ClawWork |
| 排程系統 | ✓✓ | ✓✓ | — |
| 成員與記憶 | ✓✓ | ✓✓ | — |
| CI/CD 自動部署 | ✓✓ | ✓✓ | — |
| OneStack 整合 | △ | ✓✓ | — |

---

## 已完成

### ~~P0: 緊急修復~~ ✅ 完成（2026-03-09 ~ 03-10）

| 任務 | 說明 | 狀態 |
|------|------|:----:|
| B-C1 | Gemini CLI 硬編碼路徑 | ✅ |
| B-C2 | 路徑遍歷安全漏洞 | ✅ |
| B-C3 | Semaphore 競態條件 | ✅ |
| F-C1 | Toast 直接修改 Pinia | ✅ |
| F-C2 | setInterval 未清理 | ✅ |
| F-C3 | Kanban 刪除邏輯 bug | ✅ |

### 規劃外已完成（03-09 ~ 03-13）

| 功能 | 說明 |
|------|------|
| 虛擬辦公室 | Sprite 角色系統、辦公室佈局、辦公室名稱設定 |
| 排程系統 | CronJob CRUD、暫停/啟動、手機卡片列表、專案篩選 |
| 全域專案選擇器 | Header 專案切換，各頁面共用 |
| 成員系統 | 角色、頭像、Sprite、記憶體（短期/長期） |
| GCP 部署 | CI/CD（push → tag → deploy）、熱更新 API |
| OneStack 整合 | Phase 1 設計、連線設定頁 |
| 頻道設定 UI | Settings 頁頻道設定區塊（P1 前置） |
| 手機版適配 | 響應式佈局、Kanban/CronJobs 卡片版 |
| 頁面 icon 統一 | Sidebar ↔ PageHeader icon 一致 |
| 成員收件匣 | 自動建立 AI 成員專屬列表（is_member_bound），支援跨成員丟卡片通訊 |
| Inbound 列表 | OneStack → Inbound 更名，語意更通用 |
| AI 帳號 Fallback | 主帳號失敗時自動切換備用帳號（按 priority 順序） |
| 預設路由移除 | 移除 phase_routing 遺留系統，簡化成員路由邏輯 |
| 對話框優化 | Claude JSON 解析、工具詳情顯示、UTC 時區修正、摘要 70 字 |
| Auth 中介層 | CI/CD deploy 路徑豁免認證 |

---

## 待開發

### P1: 多頻道通訊（2-3 週）⏳ 前置 UI 已完成
| 頻道 | 技術 | 說明 | 狀態 |
|------|------|------|:----:|
| Telegram | python-telegram-bot | 建卡、查詢、中止 | 待開發 |
| LINE | line-bot-sdk | 復用牧陽小通 | 待開發 |
| Discord | discord.py | 團隊協作 | 待開發 |

### P2: 擴展 LLM（1-2 週）
| LLM | 優先級 | 說明 |
|-----|-------|------|
| OpenAI GPT-4o | 高 | 通用能力 |
| DeepSeek | 高 | 性價比高 |
| Ollama | 高 | 離線能力 |
| OpenRouter | 中 | 一個 API 接入 41+ 模型 |
| 智谱/通義 | 低 | 中國市場 |

### P3: 智能路由（1-2 週）
| 任務類型 | 推薦模型 | 備援 |
|---------|---------|------|
| 簡單查詢 | DeepSeek | GPT-4o-mini |
| 代碼生成 | Claude | GPT-4o |
| 架構設計 | Gemini | Claude |
| 代碼審查 | Claude | DeepSeek |
| 文檔生成 | GPT-4o-mini | DeepSeek |

### P4: 安全機制（1-2 週）
| 功能 | 參考 |
|------|------|
| 提示注入防禦 | IronClaw SafetyLayer |
| 敏感資料洩漏檢測 | IronClaw LeakDetector |
| 工具輸出清洗 | Spacebot |
| API 速率限制 | ZeroClaw |

### P5: 向量搜索（2-3 週）
| 組件 | 選型 |
|------|------|
| Embedding | OpenAI text-embedding-3-small |
| 向量存儲 | LanceDB（輕量）或 Qdrant |
| 搜索算法 | 混合搜索 (FTS + Vector + RRF) |

### P6: 容器隔離（2-3 週）
| 功能 | 說明 |
|------|------|
| Docker 執行 | AI 任務在容器中運行 |
| 網路白名單 | 限制可訪問的域名 |
| 憑證注入 | 安全傳遞 API Key |
| 資源限制 | CPU/RAM/時間限制 |

### P7: CLI 工具（1 週）
```bash
aegis init              # 初始化專案
aegis card create       # 建立卡片
aegis card list         # 列出卡片
aegis run <card_id>     # 手動執行
aegis status            # 系統狀態
aegis logs <card_id>    # 查看日誌
aegis cron list/add/rm  # 排程管理
```

### P8: 技能系統（2 週）
| 功能 | 說明 |
|------|------|
| SKILL.md 格式 | 標準化技能定義 |
| 本地註冊表 | Skills 管理 |
| MCP 協議 | 外部工具整合 |

### P9: 瀏覽器自動化（1-2 週）
| 功能 | 技術 |
|------|------|
| 網頁操作 | Playwright |
| 截圖 | Playwright screenshot |
| 表單填寫 | Playwright fill |

### P10: 多代理協作（2-3 週）
| 功能 | 參考 |
|------|------|
| Agent 間訊息 | TinyClaw `[@agent: msg]` |
| 任務分解 | Spacebot Branch/Worker |
| 結果聚合 | Spacebot Compactor |

---

## 路線圖

```
2026 Q1 (3月)
├── Week 1-2: P0 緊急修復 ✅
├── Week 2-3: 虛擬辦公室 + 排程 + 部署 ✅
├── Week 3-4: P1 多頻道通訊（後端接入）
└── Week 5-6: P2 擴展 LLM

2026 Q2 (4-6月)
├── Month 1: P3 智能路由 + P4 安全機制
├── Month 2: P5 向量搜索
└── Month 3: P6 容器隔離

2026 Q3 (7-9月)
├── Month 1: P7 CLI + P8 技能系統
├── Month 2: P9 瀏覽器自動化
└── Month 3: P10 多代理協作
```

---

## 快速勝利

| 建議 | 原因 |
|------|------|
| P1 多頻道 | 復用 HappyNAS Bot 代碼，前端 UI 已完成 |
| P2 OpenRouter | 一個 API 接入 41+ 模型 |
| P4 安全機制 | 直接參考 IronClaw |

---

## 整合建議

| 現有系統 | 整合方式 | 狀態 |
|---------|---------|:----:|
| HappyNAS | 復用 LINE/Telegram Bot | 待開發 |
| AutoDev | Aegis 作為 Web UI | ✅ 運作中 |
| Trello | 保留整合，Aegis 執行 | ✅ 運作中 |
| OneStack | 雙向同步（Phase 1-3） | △ 規劃中 |

---

*完整版：`FEATURE-ROADMAP.md`*
