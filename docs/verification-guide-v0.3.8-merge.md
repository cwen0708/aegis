# Aegis v0.3.8 Merge 驗證手冊

> 本次合併包含 22 個功能 + 3 項安全修正，共 52 個檔案變更。
> 驗證環境：本地 `uvicorn`(:8899) + `pnpm dev`

---

## 快速啟動

```bash
# 後端
cd backend
pip install -r requirements.txt   # 新增 GitPython
uvicorn app.main:app --port 8899 --reload

# 前端
cd frontend
pnpm install                       # 新增 dompurify
pnpm dev
```

---

## 1. Token 用量儀表板（UsageDashboard）

**頁面**：側邊欄 Settings → Usage，或直接 `/settings/usage`

**預期看到**：
- 上方 4 張摘要卡片（Total Tasks / Input Tokens / Output Tokens / Cost）
- 篩選列：分群（日期/成員/供應商）× 時間範圍（7/30/90 天）
- 資料表格：依選擇的分群維度顯示統計

**操作驗證**：
| 操作 | 預期結果 |
|------|---------|
| 切換「按日期」 | 表格按日期列出每天的 token 用量 |
| 切換「按成員」 | 表格按 AI 成員名稱聚合 |
| 切換「按供應商」 | 表格按 claude/gemini/openai 聚合 |
| 切換時間範圍 | 摘要卡片數字跟著變動 |
| 無資料時 | 顯示「暫無資料」空狀態，不報錯 |

**API**：`GET /api/v1/members/usage-dashboard?group_by=date&days=7`

---

## 2. Artifacts 預覽（CardDetailDialog）

**頁面**：任一卡片詳情 → 新增的「Artifacts」分頁

**前提**：卡片的 workspace 目錄下有產出物（HTML/圖片/Markdown/PDF）

**預期看到**：
- 左側檔案清單（名稱 + 大小）
- 右側預覽區

**操作驗證**：
| 操作 | 預期結果 |
|------|---------|
| 點擊 `.html` 檔案 | sandboxed iframe 載入，腳本受限 |
| 點擊 `.png/.jpg` 檔案 | 圖片置中顯示 |
| 點擊 `.md` 檔案 | Markdown 渲染為 HTML（經 DOMPurify 過濾） |
| 點擊 `.pdf` 檔案 | PDF iframe 嵌入預覽 |
| workspace 無檔案 | 空清單，不報錯 |

**XSS 安全驗證**（可選）：
- 在 workspace 放一個含 `<script>alert(1)</script>` 的 `.md` 檔
- 預覽時不應跳出 alert

**API**：
- `GET /api/v1/cards/{id}/artifacts` → 檔案清單
- `GET /api/v1/cards/{id}/artifacts/raw?path=xxx` → 原始檔案

---

## 3. 對話歷史管理（ConversationManager）

**影響**：Telegram/LINE 聊天

**驗證方式**：透過 Telegram 跟任一 AI 成員聊天

**操作驗證**：
| 操作 | 預期結果 |
|------|---------|
| 連續對話 3+ 輪 | AI 回覆有記住前文，引用先前的話題 |
| 過了一段時間再聊 | 仍然記得最近的對話歷史（最多 25 則） |

**技術確認**：`get_chat_history(session_id, limit=25)` 回傳按時間排序的對話紀錄

---

## 4. Error Classifier（錯誤分類 + 智慧重試）

**影響**：Worker 任務失敗時的處理邏輯

**驗證方式**：觀察 Worker 日誌

**操作驗證**：
| 錯誤類型 | 預期行為 |
|---------|---------|
| 套件缺失（ModuleNotFoundError） | 標記 `dependency_missing`，不重試 |
| 語法錯誤（SyntaxError） | 標記 `syntax_error`，不重試 |
| API 限流（rate limit / 529） | 標記 `api_error`，自動重試 |
| 執行超時 | 標記 `timeout`，自動重試 |
| 權限拒絕 | 標記 `permission_denied`，不重試 |

**日誌關鍵字**：搜尋 `ErrorClassification` 或 `classify_error`

---

## 5. Worker 任務超時機制

**影響**：PTY 模式執行的卡片任務

**預設超時**：3600 秒（1 小時）

**驗證方式**：
- 建立一張會長時間跑的測試卡片
- 觀察是否在超時後自動終止

**預期結果**：
- 日誌出現 `Timeout after {N}s, killing PTY process`
- 卡片狀態變更為 `timeout`
- 前端串流輸出顯示 `⏰ 任務超時（已執行 N 秒），強制終止`
- PTY 進程使用 `terminate(force=True)` 安全終止（不再用 SIGKILL）

---

## 6. 語義搜索 + Embedding

**API 端點**：

| 端點 | 功能 |
|------|------|
| `GET /api/v1/members/{slug}/memory/search?q=關鍵字&mode=bm25` | BM25 文字搜索 |
| `GET /api/v1/members/{slug}/memory/search?q=關鍵字&mode=vector` | 向量語義搜索 |
| `GET /api/v1/members/{slug}/memory/search?q=關鍵字&mode=hybrid` | 混合搜索（BM25 + vector） |
| `POST /api/v1/members/backfill-embeddings` | 批次補建 embedding |

**驗證方式**（curl）：
```bash
# BM25 搜索（不需要 OpenAI key）
curl "http://localhost:8899/api/v1/members/aegis/memory/search?q=部署&mode=bm25"

# Vector 搜索（需要 OPENAI_API_KEY 環境變數）
curl "http://localhost:8899/api/v1/members/aegis/memory/search?q=部署&mode=vector"
```

**預期結果**：
- `bm25` 模式：一定有結果（純文字匹配）
- `vector` 模式：需要有 embedding 資料，無 API key 時回傳空陣列（不報錯）
- `hybrid` 模式：合併 bm25 + vector 結果，RRF 排序

---

## 7. 結構化記憶 CRUD

**API 端點**：

| 端點 | 功能 |
|------|------|
| `GET /api/v1/members/{slug}/memory` | 列出所有記憶檔案 |
| `DELETE /api/v1/members/{slug}/memory/{filename}` | 刪除指定記憶 |
| `PUT /api/v1/members/{slug}/memory/{filename}` | 更新記憶內容 |

**驗證方式**（curl）：
```bash
# 列出記憶
curl "http://localhost:8899/api/v1/members/aegis/memory"

# 刪除（注意 filename 不能含 .. 或 /）
curl -X DELETE "http://localhost:8899/api/v1/members/aegis/memory/test.md"
```

**安全驗證**：
```bash
# path traversal 應被擋住
curl -X DELETE "http://localhost:8899/api/v1/members/aegis/memory/..%2F..%2Fetc%2Fpasswd"
# 預期：400 Bad Request
```

---

## 8. Backlog 任務鎖定（block_similar_cards）

**影響**：Worker 開始執行卡片時，自動封鎖同 milestone 中標題相似的卡片

**驗證方式**：
1. 在同一個 milestone 下建兩張標題相似的卡片（如「新增用戶註冊功能」和「新增用戶登入功能」）
2. 讓 Worker 開始執行其中一張
3. 檢查另一張是否被標記為 `blocked`

**日誌關鍵字**：`block_similar_cards` 或 `Blocked`

---

## 9. Provider Failover Chain

**影響**：當主要 AI 供應商（如 Claude）所有帳號都失敗時

**Failover 順序**：
- Claude → Gemini → OpenAI
- Gemini → Claude → OpenAI
- OpenAI → Claude → Gemini

**驗證方式**：
- 暫時停用 Claude API key，觀察是否自動切換到 Gemini
- 日誌搜尋 `failover` 或 `get_failover_chain`

**注意**：Failover 使用系統預設 API key（環境變數），不會使用成員帳號

---

## 10. 成本感知模型路由

**影響**：卡片任務自動選擇模型等級

**路由規則**（優先級 tag > complexity > default）：

| 條件 | 選擇模型 |
|------|---------|
| Tag: `AI-Opus` 或 `complex` | Opus |
| Tag: `AI-Sonnet` | Sonnet |
| Tag: `AI-Haiku`, `simple`, `Refactor` | Haiku |
| Prompt > 2000 字 或含架構設計關鍵字 | Opus |
| Prompt 500-2000 字 或含程式修改關鍵字 | Sonnet |
| Prompt < 500 字且無複雜指標 | Haiku |

**驗證方式**：
- 建立帶 `AI-Haiku` tag 的卡片 → 日誌應顯示使用 haiku 模型
- 建立內容很長的卡片（無 tag）→ 應自動升級到 sonnet/opus

---

## 11. Git 自動備份

**API**：`POST /api/v1/system/git-backup`

**驗證方式**：
```bash
curl -X POST "http://localhost:8899/api/v1/system/git-backup"
```

**預期結果**：
- 有未提交變更時：回傳 `{"status": "ok", "message": "backup created"}`
- 無變更時：回傳 `{"status": "ok", "message": "nothing to backup"}`
- 會在專案目錄產生一筆 git commit

---

## 12. LLM Audit Logger

**日誌路徑**：`data/llm_audit.jsonl`（backend 上層目錄）

**驗證方式**：
1. 執行任一 AI 任務（聊天或卡片）
2. 檢查 `data/llm_audit.jsonl` 是否有新行

**每行 JSON 包含**：
```json
{
  "provider": "claude",
  "model": "sonnet",
  "card_id": 123,
  "duration_ms": 5000,
  "input_tokens": 1000,
  "output_tokens": 500,
  "status": "success"
}
```

---

## 13. EventLogHook（任務事件回放基礎）

**日誌路徑**：`{project}/.aegis/cards/card-{id}.events.jsonl`

**驗證方式**：
1. 執行一張卡片任務
2. 到卡片的 workspace 目錄檢查 `.aegis/cards/` 下是否有 `.events.jsonl`

**事件類型**：`tool_call`、`text`、`result`、`output`

---

## 14. MemberMessage（AI 成員通訊）

**API**：

```bash
# 發送訊息
curl -X POST "http://localhost:8899/api/v1/member-messages" \
  -H "Content-Type: application/json" \
  -d '{"from_member_id": 1, "to_member_id": 2, "message_type": "info", "content": "測試訊息"}'

# 查詢訊息
curl "http://localhost:8899/api/v1/member-messages?from_member_id=1&limit=10"
```

**預期結果**：POST 回傳建立的訊息物件，GET 回傳訊息列表

---

## 15. 閒時偵測（IdleDetector）

**影響**：CronPoller 使用，判斷系統是否閒置以決定是否執行排程任務

**閒置條件（全部滿足才算閒置）**：
- CPU ≤ 80%
- 無 running/pending 卡片
- 最近 5 分鐘無聊天訊息
- ProcessPool 無活躍進程

**驗證方式**：觀察 CronPoller 日誌中的 idle 判斷

---

## 16. Leader-Worker 委派

**API**：`POST /api/v1/cards/{card_id}/delegate`

```bash
curl -X POST "http://localhost:8899/api/v1/cards/100/delegate" \
  -H "Content-Type: application/json" \
  -d '{"target_member_id": 2, "title": "子任務標題", "content": "子任務描述"}'
```

**預期結果**：
- 在目標成員的 Inbox 建立新卡片
- 新卡片的 `parent_id` 指向原始卡片
- 產生一筆 MemberMessage 記錄委派關係

**查詢子任務**：`GET /api/v1/cards/100/subtasks`

---

## 17. Prompt Hardening（安全注入）

**影響**：所有 AI 任務和聊天

**驗證方式**：
- 卡片任務的 prompt 前方會注入完整版安全提醒（~150 tokens）
- 聊天的每則訊息前注入精簡版（~60 tokens）

**技術確認**：日誌中搜尋 `harden_prompt` 或 `harden_message`

---

## 18. Data Classifier Guard

**影響**：阻擋含敏感資料（API key、密碼等）的 prompt 送出

**驗證方式**：
- 在聊天中嘗試貼上看起來像 API key 的字串
- S3 等級（高度敏感）：任務應被阻擋，回傳錯誤
- S2 等級（中度敏感）：資料被遮蔽後繼續執行

---

## 19. 資料模型新增

**新增 2 張表**（SQLite 自動建立）：
- `MemberMessage`：AI 成員間訊息
- `EmbeddingRecord`：記憶向量索引

**`CardIndex` 新增欄位**（已在先前版本加入）：
- `parent_id`：委派關係
- `cron_job_id`：排程關聯

**驗證**：啟動後端，SQLite 應自動 migrate，不報錯

---

## 20. OpenAI Stream Chat 腳本

**檔案**：`backend/scripts/openai_stream_chat.py`

**用途**：OpenAI provider 的串流對話腳本，由 Worker 呼叫

**驗證方式**：設定 `OPENAI_API_KEY` 後，建立使用 OpenAI provider 的卡片任務

---

## 安全修正驗證

| 修正項 | 驗證方式 |
|--------|---------|
| XSS（DOMPurify） | Artifacts 的 Markdown 預覽不執行 `<script>` |
| PTY terminate | Worker 超時/中止時進程正常終止（日誌無 SIGKILL） |
| 死碼清除 | `chat_handler.py` 不再有 `_build_chat_prompt` 函式 |

---

## 驗證 Checklist

- [ ] 後端啟動正常（無 import error）
- [ ] 前端啟動正常（無 build error）
- [ ] `/settings/usage` 頁面正常顯示
- [ ] 卡片詳情 Artifacts tab 可見
- [ ] Telegram 聊天有對話歷史
- [ ] 記憶搜索 API 可用（bm25 模式）
- [ ] `data/llm_audit.jsonl` 有寫入
- [ ] Worker 超時機制生效
- [ ] 全部 565 個測試通過
