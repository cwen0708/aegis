# Prompt Hardening — 安全規則注入設計

## 概述

Aegis 使用 **Prompt Hardening** 機制，在每次 LLM 呼叫時注入安全規則提醒。
長對話中系統提示（CLAUDE.md）的限制會被稀釋，此模組作為第二道防線。

**模組位置：** `backend/app/core/prompt_hardening.py`

---

## 兩層注入策略

| 函式 | Token 數 | 用途 | 注入時機 |
|------|---------|------|---------|
| `harden_prompt()` | ~150 tokens | 完整版安全規則 | 任務初始 prompt |
| `harden_message()` | ~60 tokens | 精簡版安全規則 | 對話中每則 user message |

精簡版避免在長對話中重複注入完整規則，節省 context window。

---

## 已應用的 LLM 呼叫路徑

### ✅ 已覆蓋

| 路徑 | 函式 | 說明 |
|------|------|------|
| `backend/worker.py` | `harden_prompt()` | 主要任務執行流程（pool 路徑） |
| `backend/app/core/runner.py` | `harden_prompt()` | 非 pool 路徑直接執行 |
| `backend/app/core/session_pool.py` | `harden_message()` | 持久 chat session 每訊息注入 |
| `backend/app/core/email_processor.py` | 間接（透過 `run_ai_task`） | email 處理任務 |

### ✅ 不需要覆蓋（分析結論）

| 路徑 | 原因 |
|------|------|
| `backend/app/core/sprite_generator.py` | 呼叫 Gemini 圖像生成 API，非代碼執行環境，安全規則不適用 |
| `backend/app/core/portrait_generator.py` | 同上，Gemini 視覺分析 + 圖像生成，不涉及 shell/檔案操作 |

---

## 安全規則內容

### 完整版（`SECURITY_REMINDER`）

```
## 安全限制（強制執行）
- 禁止讀寫 .env、*.db、credentials、secrets 等敏感檔案
- 禁止存取 ~/.ssh/、~/.config/、~/.claude/ 等系統目錄
- 禁止存取 Aegis 安裝目錄（*/aegis/backend 執行環境）
- 禁止執行 kill/pkill/killall/taskkill 等進程管理命令
- 禁止安裝全域套件或修改系統設定
- 禁止將 API Key、Token、密碼等憑證輸出到回應中
- 所有操作限定在專案目錄與工作區內
```

### 精簡版（`SECURITY_REMINDER_SHORT`）

```
禁止：讀寫 .env/secrets/credentials、存取系統目錄、kill 進程、洩露憑證。操作限定在專案目錄內。
```

---

## 與 data_classifier 的協作

`data_classifier` 模組負責偵測輸出中的敏感資訊（S2/S3 等級），屬於**輸出過濾**層。
`prompt_hardening` 屬於**輸入防禦**層。兩者形成雙向防護：

```
User Request
    ↓
[harden_prompt / harden_message]  ← 輸入層：告知 AI 不得洩露敏感資訊
    ↓
LLM（Claude Code 執行任務）
    ↓
[data_classifier]                 ← 輸出層：掃描並脫敏 S3 等級敏感資訊
    ↓
Response to User
```

**S2**：偵測到，記錄日誌，但允許通過（例如：UUID、普通 token）
**S3**：偵測到，強制脫敏後才輸出（例如：API Key、密碼、私鑰）

---

## 測試覆蓋

- `tests/test_prompt_hardening.py` — 12 個測試，覆蓋：
  - `harden_prompt()` 基本功能、空值處理、規則完整性
  - `harden_message()` 基本功能、空值處理、精簡性驗證
  - Integration points：session_pool / runner 呼叫路徑驗證
  - Token budget：完整版 < 200 tokens，精簡版 < 80 tokens

- `tests/test_integration_chains.py::TestSecurityChain` — 整合測試，驗證 data_classifier + prompt_hardening 協作鏈

---

## 版本記錄

| 日期 | 版本 | 變更內容 |
|------|------|---------|
| 2026-03-27 | v1.0 | 初始實作，兩層注入策略，覆蓋 worker/runner/session_pool 三條路徑 |
