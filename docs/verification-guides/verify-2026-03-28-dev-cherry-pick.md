# 驗證手冊：2026-03-28 Dev Cherry-pick

> 從 dev 分支 cherry-pick 8 個 commit 到 merge（跳過 1 個重複）
> 移除 1 個多餘檔案（package-lock.json）

---

## 合併摘要

| Commit | 類型 | 說明 |
|--------|------|------|
| `008813d` | feat | Git Worktree 隔離 — 工具模組 + workspace 整合 |
| `6cf08b2` | docs | Watchdog Step 2 設計文件 |
| `87ac1f6` | fix | guard_for_ai() redact_map 被丟棄問題修復 |
| `df05a75` | feat | 擴充 S3 偵測規則（+4 種敏感資料類型） |
| `7d852e4` | feat | 精確重試計數與上限控制（MAX_RETRY_ATTEMPTS=3） |
| `4005f54` | docs | Watchdog Step 2 補充設計（pre-check、邊界案例） |
| `4b261dd` | feat | per-project 自訂去敏化規則（desensitize.yaml） |
| `d3b0e87` | docs | Prompt Hardening 安全注入設計文件 |
| — | chore | 移除多餘 package-lock.json（專案用 pnpm） |
| `99f4de0` | skip | test_card_watcher 修復（與 main 重複，已跳過） |

**影響檔案**：11 個（扣除 package-lock.json 後為 10 個）

---

## 1. Data Classifier — S3 偵測規則擴充

**檔案**：`backend/app/core/data_classifier.py`

**新增 4 種偵測 Pattern**：

| 名稱 | 偵測對象 | 範例 |
|------|---------|------|
| `db_connection_string` | 含密碼的 DB 連線字串 | `postgresql://user:pass@host` |
| `pem_private_key` | PEM 私鑰標頭 | `-----BEGIN RSA PRIVATE KEY-----` |
| `gcp_api_key` | Google Cloud API 金鑰 | `AIzaSy...` |
| `slack_token` | Slack API token | `xoxb-...` |

**驗證方式**（curl / 測試）：

```bash
# 跑 data_classifier 測試
cd backend && C:/Python312/python.exe -m pytest tests/test_data_classifier.py -v --tb=short
```

**手動驗證**：在聊天中嘗試貼上以下內容，應被阻擋（S3）：
- `postgresql://admin:secret123@db.example.com/mydb`
- `-----BEGIN RSA PRIVATE KEY-----`
- `AIzaSyA1234567890abcdefghijklmnopqrstuvw`
- `xoxb-1234567890-abcdefghij`

**預期結果**：回傳 `SecurityBlock` 錯誤，不送往 AI

---

## 2. guard_for_ai() redact_map 修復

**檔案**：`backend/app/core/data_classifier.py`、`backend/app/core/runner.py`、`backend/app/core/session_pool.py`

**問題**：之前 guard_for_ai() 的 redact_map 在 runner/session_pool 中未正確傳遞，導致 AI 回應中的 `<<REDACTED:xxxxx>>` 佔位符無法還原。

**修復流程**：
1. `guard_for_ai(prompt, project_path)` → 回傳 `(sanitized_prompt, redact_map)`
2. AI 回應後 `restore(output, redact_map)` → 佔位符還原為原始值

**驗證方式**：
1. 在聊天中貼含 S2 等級資料（如 email `test@example.com`）
2. AI 收到的 prompt 中 email 應被替換為 `<<REDACTED:xxxxx>>`
3. AI 回應中如引用該 email，佔位符應被還原為原始值

**測試**：
```bash
cd backend && C:/Python312/python.exe -m pytest tests/test_sanitize_output.py -v --tb=short
```

---

## 3. Worker 精確重試計數（MAX_RETRY_ATTEMPTS=3）

**檔案**：`backend/worker.py`

**機制**：
- 重試上限：`MAX_RETRY_ATTEMPTS = 3`
- 計數方式：計算卡片 content 中 `### Error (retry` 出現的次數
- 每次重試在 content 追加 `### Error (retry N/3)`
- 超過 3 次 → 標記為最終 `failed`

**驗證方式**：
1. 建立一張會失敗的卡片（如故意引用不存在的套件）
2. 觀察 Worker 日誌中的重試行為

| 情境 | 預期行為 |
|------|---------|
| 可重試錯誤（API timeout） | 自動重試，最多 3 次 |
| 不可重試錯誤（syntax error） | 直接 failed，不重試 |
| 已重試 3 次 | 標記最終 failed，不再重試 |

**測試**：
```bash
cd backend && C:/Python312/python.exe -m pytest tests/test_worker_retry_count.py -v --tb=short
```

---

## 4. Per-Project 自訂去敏化規則

**檔案**：`backend/app/core/data_classifier.py`、`docs/examples/desensitize.yaml`

**機制**：每個專案可在 `.aegis/desensitize.yaml` 定義自訂偵測規則

**YAML 格式**：
```yaml
patterns:
  - name: deploy_key        # 規則名稱
    regex: "DEPLOY-[A-F0-9]{32}"  # Python re 語法
    level: S3                # S3=阻擋, S2=去敏化
  - name: employee_id
    regex: "EMP-\\d{6}"
    level: S2
```

**驗證方式**：
1. 在某專案目錄建立 `.aegis/desensitize.yaml`
2. 定義一個自訂 S3 規則
3. 在該專案的聊天中貼上匹配的字串
4. 應被阻擋（S3）或去敏化（S2）

**範例檔參考**：`docs/examples/desensitize.yaml`

---

## 5. 設計文件（僅文件，無需功能驗證）

| 文件 | 路徑 | 內容 |
|------|------|------|
| Watchdog Step 2 | `docs/plans/2026-03-26-watchdog-step2-design.md` | idle-aware 自動重啟、三階段 pre-check |
| Prompt Hardening | `docs/prompt-hardening.md` | 安全注入設計說明 |

可略讀確認內容合理即可。

---

## 6. Git Worktree 隔離

**檔案**：`frontend/package-lock.json`（已移除）

此 commit 原含一個 4455 行的 `package-lock.json`，因專案使用 pnpm 而非 npm，已在後續 commit 移除。

**驗證**：確認 `frontend/package-lock.json` 不存在即可。

---

## 測試結果

```
600 passed in 18.54s
241 routes OK
```

---

## Checklist

- [ ] 後端啟動正常（`uvicorn` 無 import error）
- [ ] `test_data_classifier.py` 通過
- [ ] `test_sanitize_output.py` 通過
- [ ] `test_worker_retry_count.py` 通過
- [ ] S3 偵測：DB 連線字串被阻擋
- [ ] S3 偵測：PEM 私鑰被阻擋
- [ ] S2 去敏化：email 被替換為佔位符，AI 回應後還原
- [ ] Worker 重試：失敗任務最多重試 3 次
- [ ] `frontend/package-lock.json` 已不存在
- [ ] 設計文件可正常閱讀
