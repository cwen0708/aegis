# 後端 Backlog 大任務拆分建議

**日期**：2026-03-31
**執行者**：小茵（Aegis 自我開發分析師）
**原始卡片**：#12348 — chore: Backlog 大任務拆分 — 前端 + 後端分批
**執行卡片**：#12365

---

## 掃描範圍

- 列表：AEGIS 專案 Backlog（list_id=49）
- 總卡片數：62 張（未封存）
- 篩選條件：後端相關、預估 > 2 小時、排除 P0/P1/M 系列

---

## 識別結果：7 張可拆分後端卡片

### 卡片 #11671 — feat: Embedding 服務 + 向量儲存層 + Executor 整合

| 欄位 | 內容 |
|------|------|
| 原標題 | feat: Embedding 服務 + 向量儲存層 + Executor 整合 |
| 原估工時 | ~4–6 小時 |
| 優先順序 | 高（里程碑 #11008） |
| 技術依賴 | OpenAI text-embedding API、SQLite、executor/context.py |

**拆分方案（4 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | core/embedding.py — 封裝 text-embedding-3-small，提供 get_embedding() 介面 | 25 分鐘 | 無 |
| B | SQLite 向量儲存表 — 建立 embeddingrecord schema + CRUD | 25 分鐘 | A |
| C | 記憶寫入 Hook — on_complete 時觸發 embedding 寫入 | 30 分鐘 | A, B |
| D | Executor 整合 — 任務啟動時 top-K 相關記憶注入 system prompt | 30 分鐘 | B, C |

備註：B 的 schema 已存在（embeddingrecord 表），需確認是否需要補 vector_blob 欄位。

---

### 卡片 #11339 — 三層安全沙箱（Landlock+seccomp+netns）

| 欄位 | 內容 |
|------|------|
| 原標題 | 三層安全沙箱（Landlock+seccomp+netns） |
| 原估工時 | ~6–8 小時 |
| 優先順序 | P2，security |
| 技術依賴 | Linux kernel（Landlock 5.13+、seccomp、netns）、sandbox.py、GCP VM |

**拆分方案（4 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | GCP VM 相容性評估 — 確認 kernel 版本支援 Landlock/seccomp/netns | 20 分鐘 | 無 |
| B | seccomp 過濾器 — 在 sandbox.py 注入危險 syscall 黑名單 | 30 分鐘 | A |
| C | Landlock 檔案系統限制 — 限制 worker 只能存取 workspace 目錄 | 30 分鐘 | A |
| D | netns 網路隔離 — 將 sandbox 進程移入獨立 network namespace | 45 分鐘 | A, B, C |

備註：A 是風險把關關鍵步驟，若 kernel 不支援需改為純 Python 降級方案。

---

### 卡片 #11332 — 自我修復 Pipeline

| 欄位 | 內容 |
|------|------|
| 原標題 | 自我修復 Pipeline |
| 原估工時 | ~4–5 小時 |
| 優先順序 | P2，reliability |
| 技術依賴 | runner.py、task_result.py、hooks/、錯誤日誌 |

**拆分方案（4 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | 失敗偵測 Hook — on_fail 偵測 exit_code != 0 + timeout，記錄錯誤類型 | 25 分鐘 | 無 |
| B | 錯誤日誌分類器 — 分析 stderr 判斷失敗類型（network/code/env/timeout） | 30 分鐘 | A |
| C | 自動修復嘗試 — 依失敗類型執行對應修復策略（retry/cleanup/rollback） | 30 分鐘 | B |
| D | 修復失敗通知 — 二次失敗後更新卡片狀態 + 觸發人工通知 | 20 分鐘 | C |

備註：B 已有 error_classifier.py 基礎，可直接擴充。

---

### 卡片 #11874 — Per-card Cost Tracking（借鑑 ECC）

| 欄位 | 內容 |
|------|------|
| 原標題 | Per-card Cost Tracking（借鑑 ECC） |
| 原估工時 | ~3–4 小時 |
| 優先順序 | P2，observability |
| 技術依賴 | CardIndex、hooks/、claude_usage.py、cost_calculator.py |

**拆分方案（3 後端 + 1 前端）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 | 類型 |
|--------|------|----------|----------|------|
| A | Token 計數 Hook — on_complete 時抓取 usage，累計 input/output tokens | 25 分鐘 | 無 | 後端 |
| B | CardIndex 欄位更新 — 確保 total_input_tokens / estimated_cost_usd 正確寫入 | 20 分鐘 | A | 後端 |
| C | 成本查詢 API — GET /cards/{id} 回傳成本；GET /projects/{id}/cost 統計 | 30 分鐘 | B | 後端 |
| D | 前端費用顯示 — UsageDashboard 顯示每成員/每專案累計費用 | 45 分鐘 | C | 前端 |

備註：CardIndex 已有 total_input_tokens、estimated_cost_usd 欄位，後端主要工作是確保 hook 正確填入。

---

### 卡片 #11323 — 自動去敏化處理

| 欄位 | 內容 |
|------|------|
| 原標題 | 自動去敏化處理 |
| 原估工時 | ~3–4 小時 |
| 優先順序 | P2，security, privacy |
| 技術依賴 | data_classifier.py、executor/context.py、prompt_hardening.py |

**拆分方案（3 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | 規則引擎 — 正則偵測 S2 資料（地址/電話/信箱/姓名），替換為 PLACEHOLDER_N | 30 分鐘 | 無 |
| B | 還原器 — AI 回應後將佔位符還原為原始值，支援嵌套替換 | 25 分鐘 | A |
| C | Per-project 設定 — SystemSetting 可自訂去敏化規則（開關、自訂欄位） | 25 分鐘 | A, B |

備註：data_classifier.py 已有 S1/S2/S3 分類基礎，A 可直接擴充。

---

### 卡片 #11337 — Named Session 平行工作流

| 欄位 | 內容 |
|------|------|
| 原標題 | Named Session 平行工作流 |
| 原估工時 | ~5–6 小時 |
| 優先順序 | P2，parallel-execution |
| 技術依賴 | session_pool.py、runner.py、worker.py、CardIndex |

**拆分方案（4 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | 設計文件 — 定義 session 命名規則、slot 上限、與卡片的對應關係 | 20 分鐘 | 無 |
| B | Session 命名建立 — session_pool.py 支援 per-card 命名 session | 30 分鐘 | A |
| C | Session 持久化 — 記錄 session_id 到 CardIndex，支援中斷後恢復 | 30 分鐘 | B |
| D | Runner 整合 — runner.py 啟動時優先恢復已有 named session | 25 分鐘 | C |

備註：此卡高度依賴 runner.py/session_pool.py 的現有架構，A 的設計文件必須先做。

---

### 卡片 #11463 — test: context window 優化鏈端到端整合測試

| 欄位 | 內容 |
|------|------|
| 原標題 | test: context window 優化鏈端到端整合測試 |
| 原估工時 | ~2–3 小時 |
| 優先順序 | P2，testing |
| 技術依賴 | conversation_manager.py、model_router.py、stream_parsers.py |

**拆分方案（3 子卡片）：**

| 子任務 | 描述 | 預估時間 | 前置依賴 |
|--------|------|----------|----------|
| A | 測試場景 1 — 長對話觸發壓縮後路由到不同模型，驗證 context 在限制內 | 25 分鐘 | 無 |
| B | 測試場景 2 — 壓縮 + 裁剪同時觸發的邊界情況 | 25 分鐘 | 無 |
| C | 測試場景 3 — idle worker 上的長對話排程（測試環境設定） | 30 分鐘 | 無 |

備註：三個場景相互獨立，可並行開發。

---

## 拆分摘要

| 卡片 ID | 原標題（縮） | 原工時 | 子卡數 | 後端子卡數 | 優先序 |
|---------|------------|--------|--------|------------|--------|
| #11671 | Embedding 服務 + 向量儲存 + Executor | 4–6h | 4 | 4 | 高（里程碑） |
| #11874 | Per-card Cost Tracking | 3–4h | 4 | 3 | P2 |
| #11332 | 自我修復 Pipeline | 4–5h | 4 | 4 | P2 |
| #11339 | 三層安全沙箱 | 6–8h | 4 | 4 | P2 |
| #11323 | 自動去敏化處理 | 3–4h | 3 | 3 | P2 |
| #11337 | Named Session 平行工作流 | 5–6h | 4 | 4 | P2 |
| #11463 | context window 整合測試 | 2–3h | 3 | 3 | P2 |

合計：7 張原始卡片 → 26 張子任務（後端 25 張 + 前端 1 張），每張預估 20–45 分鐘。

---

## 技術依賴圖

```
#11671-A → #11671-B → #11671-C → #11671-D

#11332-A → #11332-B → #11332-C → #11332-D

#11339-A → #11339-B
         → #11339-C
         → #11339-D（需 B, C 完成）

#11874-A → #11874-B → #11874-C
                    → #11874-D（前端）

#11323-A → #11323-B
         → #11323-C（需 A, B）

#11337-A → #11337-B → #11337-C → #11337-D

#11463-A, B, C（三場景完全平行）
```

---

## 建議執行順序

1. **#11671（Embedding 系列）**：里程碑前置，已有部分實作，優先處理
2. **#11874（Cost Tracking）**：infrastructure 已就緒，拆分後每子卡短且獨立
3. **#11463（整合測試）**：可在主線工作間隙穿插，三場景完全獨立
4. **#11332（自我修復）**：error_classifier.py 已有基礎，可直接擴充
5. **#11323（去敏化）**：data_classifier.py 有基礎，風險低
6. **#11337（Named Session）**：需設計文件先行，稍後處理
7. **#11339（安全沙箱）**：工時最長，需先確認 GCP kernel 相容性
