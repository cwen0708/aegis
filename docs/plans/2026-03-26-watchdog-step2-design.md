# Watchdog Step 2：idle-aware 自動重啟機制設計

> Backlog #11464 | 2026-03-26 | Author: 小茵

## 概述

AEGIS 已有 `idle_detector.py`（4 信號源偵測閒置）和 `heartbeat.py`（任務執行心跳），
但缺少 worker 層級的自動重啟機制。當 worker 子進程卡死（非 idle 卻無心跳）時，
系統無法自動恢復。本文件設計一個 Watchdog 模組，利用現有 idle + heartbeat 資訊，
實現「疑似卡死」的自動偵測與分級重啟。

---

## Chapter 1: idle 狀態判定標準

### 1.1 現有 4 個信號源

`idle_detector.py` 的 `get_idle_status()` 檢查以下信號源，全部通過才判定為 idle：

| # | 信號源 | 忙碌條件 | 來源 |
|---|--------|---------|------|
| 1 | **CardIndex** | 存在 `status="running"` 或 `status="pending"` 的卡片 | DB 查詢 |
| 2 | **CPU 使用率** | `cpu_percent >= 80.0%` | `telemetry.get_system_metrics()` |
| 3 | **ChatSession** | 最近 5 分鐘內有 `last_message_at` 更新 | DB 查詢 |
| 4 | **ProcessPool** | `process_pool.active_count() > 0` | 記憶體狀態 |

回傳 `IdleStatus` dataclass：含 `is_idle`、`idle_since`、`idle_seconds`、`busy_reasons`。

### 1.2 取樣頻率

- **Worker 主迴圈**：`POLL_INTERVAL = 3` 秒（可由 DB `SystemSetting` 動態調整），idle 偵測嵌入其中
- **Watchdog 建議取樣週期**：**12 秒**（4 倍 worker 主迴圈）
  - 理由：避免與 worker 主迴圈競爭 DB 連線，同時足夠快速偵測異常
  - 過快（< 5s）：增加 DB 負擔，且 heartbeat `check_interval=5s` 本身就有延遲
  - 過慢（> 20s）：卡死偵測反應太遲

### 1.3 idle vs busy 狀態轉換閾值

Watchdog 關注的核心狀態組合：

```
                    ┌─────────────┐
         idle=true  │   IDLE      │  ← Watchdog 不介入
                    │  (正常休息)  │
                    └──────┬──────┘
                           │ 偵測到 running card
                           ▼
                    ┌─────────────┐
         idle=false │   BUSY      │  ← 正常工作，檢查心跳
        heartbeat ✓ │  (有心跳)    │
                    └──────┬──────┘
                           │ heartbeat 超時
                           ▼
                    ┌─────────────┐
         idle=false │  SUSPECTED  │  ← 疑似卡死，進入 pre-check
        heartbeat ✗ │  (無心跳)    │
                    └──────┬──────┘
                           │ pre-check 確認異常
                           ▼
                    ┌─────────────┐
                    │   RESTART   │  ← 執行重啟
                    │  (重啟中)    │
                    └─────────────┘
```

**狀態判定規則**：
- **IDLE → BUSY**：`is_idle` 從 `True` 變為 `False`（任一信號源觸發）
- **BUSY → SUSPECTED**：連續 **5 次取樣**（≈ 60 秒）heartbeat 無更新
- **SUSPECTED → RESTART**：pre-check 通過（見 Chapter 2）
- **任何狀態 → IDLE**：`is_idle` 回到 `True`，重置所有計數器

---

## Chapter 2: 「非 idle 且無心跳」重啟觸發條件

### 2.1 「疑似卡死」定義

同時滿足以下條件：

1. **系統非 idle**：`get_idle_status().is_idle == False`
2. **存在 running card**：`busy_reasons` 包含 `"running card:"`
3. **Heartbeat 超時**：該 running card 對應的 emitter 最後一次 `touch()` 距今超過 `HEARTBEAT_TIMEOUT` 秒

**`HEARTBEAT_TIMEOUT` 建議值：60 秒**
- `heartbeat.py` 的 `idle_threshold=20s` + `check_interval=5s`
- 正常任務每收到一行輸出就 `touch()`，即使 LLM 思考中也會在 20s 後觸發 `emit_heartbeat`
- 60 秒無心跳 = 3 個 heartbeat 週期未觸發，高度疑似卡死

### 2.2 冷卻與重試策略

```python
RESTART_COOLDOWNS = [60, 120, 240]  # 秒，指數遞增
MAX_RETRIES = 3
```

| 重試次數 | 冷卻時間 | 累計等待 | 說明 |
|---------|---------|---------|------|
| 第 1 次 | 60s | 60s | 首次偵測到卡死，立即重啟 |
| 第 2 次 | 120s | 180s | 等待 2 分鐘確認非暫時性問題 |
| 第 3 次 | 240s | 420s | 最後一次嘗試 |
| 第 4 次 | — | — | 放棄重啟，進入 fallback（Chapter 3）|

**重試計數器綁定 card_id**，卡片完成或 idle 狀態時重置。

### 2.3 重啟前 pre-check（三階段判斷）

在觸發重啟前，Watchdog 必須依序執行三階段檢查以排除誤判。
任一階段判定為「活躍」即中止檢查、重置 SUSPECTED 計數並 return False。

```
Stage 1: Heartbeat     Stage 2: Conversation    Stage 3: last_activity
  活躍？                  活躍？                    綜合判斷
  ├─ 是 → return False   ├─ 是 → return False     ├─ 有活動 → return False
  └─ 否 → 繼續 ──────────└─ 否 → 繼續 ────────────└─ 無活動 → return True (RESTART)
```

```python
def pre_restart_check(
    card: CardIndex,
    session: Session,
    watchdog_state: WatchdogState,
) -> tuple[bool, str]:
    """三階段 pre-check，回傳 (should_restart, reason)"""

    # ── Stage 0: 基本前置確認 ──
    fresh = session.get(CardIndex, card.card_id)
    if not fresh or fresh.status != "running":
        return False, "card no longer running"

    # 檢查是否為已知長時間操作
    long_ops = ["git clone", "npm install", "pip install", "docker build"]
    content = (fresh.content or "").lower()
    if any(op in content for op in long_ops):
        running_time = time.time() - (fresh.updated_at or fresh.created_at).timestamp()
        if running_time < 600:  # 10 分鐘內
            return False, f"long operation detected, running {running_time:.0f}s"

    now = time.time()

    # ── Stage 1: Heartbeat 檢查 ──
    # 讀取 executor/heartbeat.py 的 last_activity 時間戳
    last_hb = get_heartbeat_last_activity(fresh.card_id)
    if last_hb and (now - last_hb) < HEARTBEAT_TIMEOUT:  # 60s
        watchdog_state.retry_counts.pop(fresh.card_id, None)
        return False, f"heartbeat alive ({now - last_hb:.0f}s ago)"

    # ── Stage 2: Conversation 活躍對話檢查 ──
    # 查詢 conversation/coordinator.py 是否有該 card 相關的活躍對話 room
    active_room = get_active_conversation_room(fresh.card_id, session)
    if active_room and active_room.last_message_at:
        room_idle = now - active_room.last_message_at.timestamp()
        if room_idle < 300:  # 近 5 分鐘有活動
            watchdog_state.retry_counts.pop(fresh.card_id, None)
            return False, f"conversation active ({room_idle:.0f}s ago)"

    # ── Stage 3: last_activity_timestamp 綜合判斷 ──
    # 檢查卡片關聯的 last_activity_timestamp（見 2.3.1 更新點定義）
    last_act = get_last_activity_timestamp(fresh.card_id)
    if last_act and (now - last_act) < HEARTBEAT_TIMEOUT:
        watchdog_state.retry_counts.pop(fresh.card_id, None)
        return False, f"last_activity recent ({now - last_act:.0f}s ago)"

    # 三階段皆無活動，確認進入 RESTART
    return True, "all 3 stages confirm: no activity detected"
```

**各階段說明**：

| 階段 | 檢查目標 | 活躍閾值 | 資料來源 |
|------|---------|---------|---------|
| Stage 1 | Heartbeat 心跳 | 距今 < 60s | `executor/heartbeat.py` → `last_activity` |
| Stage 2 | 對話 room 活動 | 距今 < 300s (5min) | `conversation/coordinator.py` → `ChatSession.last_message_at` |
| Stage 3 | 綜合活動時戳 | 距今 < 60s | `last_activity_timestamp`（多來源聚合） |

### 2.3.1 last_activity_timestamp 更新點定義

`last_activity_timestamp` 是各活動來源中最晚的時間戳，由以下 4 個觸發點更新：

| # | 觸發點 | 更新時機 | 說明 |
|---|--------|---------|------|
| 1 | **LLM chunk 回應** | executor 收到 streaming output 時 | 每個 chunk 都更新，確保 streaming 期間持續有活動記錄 |
| 2 | **Tool call 完成** | MCP 或內建 tool 執行回傳時 | tool 執行結果寫回後更新 |
| 3 | **DB 寫入** | card_index sync、memory write 等 | 任何對 DB 的修改操作都視為有效活動 |
| 4 | **MCP tool call 發起** | MCP tool call 開始執行時 | 避免長時間 MCP 呼叫（如外部 API）的空窗期被誤判為卡死 |

**實作建議**：

```python
# 在 executor context 或 emitter 中維護
def touch_last_activity(card_id: int, source: str):
    """更新 last_activity_timestamp，source 用於 debug log"""
    _last_activity[card_id] = time.time()

# 各觸發點呼叫範例：
# 1. LLM streaming:  touch_last_activity(card_id, "llm_chunk")
# 2. Tool 完成:       touch_last_activity(card_id, "tool_complete")
# 3. DB 寫入:         touch_last_activity(card_id, "db_write")
# 4. MCP 發起:        touch_last_activity(card_id, "mcp_start")
```

> **設計原則**：觸發點 4（MCP 發起時）是防禦性更新 -- 當 MCP tool 呼叫外部服務需要較長時間（如 API 回應慢），發起時就更新時戳可避免等待期間被 Watchdog 誤判。

### 2.4 重啟執行流程

```
1. pre_restart_check() 通過
2. 記錄 broadcastlog：{"event": "watchdog_restart", "card_id": ..., "retry": N}
3. 終止當前進程：ProcessPool.kill(chat_key)
4. 重置 card status 為 "pending"（重新進入 worker 排程）
5. 啟動冷卻計時器
```

### 2.5 邊界案例預期行為

以下定義三個容易與 Watchdog 機制衝突的邊界案例及其預期行為：

#### Case A: Worker 等 LLM streaming 超過 timeout

**情境**：LLM 回應延遲或斷線，卡片在 streaming 階段超過 timeout（由 card-011719 timeout 機制處理）。

**預期行為**：
- **timeout 機制優先**：`card-011719` 的 timeout 邏輯先將卡片標記為 `failed`
- **Watchdog 退讓**：pre-check Stage 0 發現 `fresh.status != "running"`（已被 timeout 標為 `failed`），直接 return False
- **不重複處理**：避免 Watchdog 與 timeout 雙重處理同一張卡片，造成重複 broadcast 或狀態衝突

```
時間線：
  T+0s   LLM streaming 開始
  T+60s  Heartbeat timeout → Watchdog 進入 SUSPECTED
  T+90s  Timeout 機制觸發 → card.status = "failed"
  T+72s  Watchdog pre-check → status != "running" → 中止，不介入
```

#### Case B: Error Classifier 標記 retryable 正在重試

**情境**：Worker 的 error classifier 將錯誤標記為 retryable，worker 自身的 retry 機制正在執行中。

**預期行為**：
- **識別 retry 中狀態**：卡片 `status == "pending"` 且 `retry_count > 0` 表示 worker 正在重試
- **Watchdog 跳過**：pre-check Stage 0 發現 `status != "running"`，自動跳過
- **Watchdog 不干預 retry 流程**：等 worker retry 完成或耗盡重試次數後，若卡片再次進入 `running` 且卡死，才由 Watchdog 接管

```python
# 在 pre_restart_check Stage 0 中，已有的 status 檢查自然排除此情境：
if not fresh or fresh.status != "running":
    return False, "card no longer running"
# retry 中的卡片 status 為 "pending"，不會通過此檢查
```

#### Case C: 連續 RESTART 3 次進 fallback 後新任務進來

**情境**：某張卡片觸發 3 次 RESTART 後進入 fallback（Chapter 3），此時新卡片被分派進來。

**預期行為**：
- **fallback 後自動復位**：fallback 流程完成後，worker 狀態恢復為 IDLE，可正常接收新任務
- **計數器獨立**：新卡片擁有獨立的 `retry_counts` 和 `cooldown_until`，前一張卡片的 fallback 計數器不影響新任務
- **fallback 計數器歸零**：`WatchdogState.retry_counts[old_card_id]` 在 fallback 完成後清除

```python
# fallback 完成後的狀態清理
def on_fallback_complete(card_id: int, watchdog_state: WatchdogState):
    """fallback 流程完成後，清除該卡片的 watchdog 狀態"""
    watchdog_state.retry_counts.pop(card_id, None)
    watchdog_state.last_heartbeat.pop(card_id, None)
    watchdog_state.cooldown_until.pop(card_id, None)
    # worker 狀態自動回到 IDLE，可接收新任務
    # 新卡片的 retry_counts 從 0 開始，與前一張卡片完全獨立
```

---

## Chapter 3: 重啟失敗的 fallback 策略

### 3.1 3 次重啟失敗後的處理

當 `MAX_RETRIES` 次重啟均失敗（重啟後卡片再次進入 SUSPECTED 狀態），執行以下 fallback：

#### 3.1.1 標記卡片為 failed

```python
card.status = "failed"
card.content += f"\n\n---\n⚠️ Watchdog: {MAX_RETRIES} 次自動重啟失敗\n"
card.content += f"最後失敗時間: {datetime.now().isoformat()}\n"
card.content += f"失敗原因: heartbeat timeout after restart\n"
```

#### 3.1.2 Auto-shelve 變更

如果任務有對應的 git 工作區（task workspace），執行：
```
git stash push -m "watchdog-auto-shelve-{card_id}-{timestamp}"
```
保留工作進度，避免丟失已完成的部分修改。

### 3.2 通知機制

#### broadcastlog 記錄

```python
broadcast_log({
    "event": "watchdog_failed",
    "card_id": card.card_id,
    "title": card.title,
    "member_id": card.assignee_id,
    "retries": MAX_RETRIES,
    "diagnosis": diagnosis_summary,
})
```

#### WebSocket 推送前端

透過現有 `ws_manager` 推送即時通知：

```python
await ws_manager.broadcast({
    "type": "watchdog_alert",
    "payload": {
        "card_id": card.card_id,
        "title": card.title,
        "message": f"任務 '{card.title}' 自動重啟 {MAX_RETRIES} 次失敗，已暫停",
        "severity": "error",
    }
})
```

前端收到 `watchdog_alert` 後顯示 Toast 通知，引導使用者查看失敗卡片。

### 3.3 人工介入提示

在卡片 content 附加失敗診斷摘要：

```markdown
---
## 🔧 Watchdog 診斷報告

- **卡死偵測時間**: 2026-03-26T14:30:00
- **重啟嘗試次數**: 3
- **最後心跳時間**: 2026-03-26T14:22:15（距今 8 分鐘）
- **忙碌原因**: running card: "實作 API endpoint"
- **進程狀態**: PID 12345 已退出（exit code: -9）
- **建議操作**:
  1. 檢查任務描述是否有模糊或矛盾的指令
  2. 確認目標檔案是否被其他進程鎖定
  3. 手動將卡片移回「待辦」重新執行
```

### 3.4 降級模式

暫停該成員的新任務分派，避免連續失敗：

```python
# 在 SystemSetting 中設定成員暫停旗標
setting_key = f"member_{member_id}_paused"
# 設定值包含暫停原因和過期時間
setting_value = json.dumps({
    "reason": "watchdog_fallback",
    "card_id": card.card_id,
    "paused_at": datetime.now().isoformat(),
    "auto_resume_at": (datetime.now() + timedelta(hours=1)).isoformat(),
})
```

- **自動恢復**：1 小時後自動解除暫停（避免永久卡住）
- **手動恢復**：管理者可透過前端或 API 立即解除
- **降級期間行為**：該成員的 pending 卡片不被 `process_pending_cards()` 拾取

---

## Chapter 4: 與現有功能的依賴關係

### 4.1 heartbeat.py 心跳資料流向

```
子進程輸出一行 → touch() 重置 last_activity
                         │
                   5 秒檢查一次
                         │
                  idle >= 20 秒？
                    ├─ 否：靜默
                    └─ 是：emitter.emit_heartbeat(idle_seconds)
                              │
                         StreamEvent(kind="heartbeat")
                              │
                    ┌─────────┴─────────┐
                    │                   │
              WebSocket 推送        hooks 處理
              （前端即時顯示）    （broadcastlog 等）
```

**Watchdog 接入點**：
- 不修改 `heartbeat.py` 本身
- 在 Watchdog 取樣時，查詢 emitter 的 `last_activity` 時間戳（需新增一個查詢介面）
- 備選方案：Watchdog 監聽 broadcastlog 中的 heartbeat 事件時間

### 4.2 idle_detector.py 取樣時機

| 呼叫者 | 時機 | 用途 |
|--------|------|------|
| `worker.py` 主迴圈 | 每 3 秒 | `auto_activate_idle_cards()` 判斷是否觸發閒時任務 |
| `cron_poller.py` | cron 觸發時 | 判斷是否適合執行排程任務 |
| **Watchdog（新增）** | 每 12 秒 | 判斷系統是否「應該忙碌卻無心跳」 |

**注意事項**：
- `get_idle_status()` 每次呼叫都做 DB 查詢，Watchdog 取樣間隔不宜過短
- Watchdog 可共用 worker 的 DB `Session`，或使用獨立的短生命週期 Session
- `_idle_since` 是模組級全域變數，多執行緒存取需注意（目前 worker 是單執行緒主迴圈，Watchdog 若為獨立線程需加鎖或使用獨立的狀態追蹤）

### 4.3 model_router.py

- **無直接依賴**：Watchdog 不涉及 model 選擇邏輯
- **重啟時保留 model 選擇**：重啟流程將 card 設回 `pending`，`process_pending_cards()` 重新拾取時會從卡片的 `.model` 欄位讀取原始 model 設定
- **無需額外處理**：model 資訊持久化在 DB，不隨進程重啟而遺失

### 4.4 worker.py startup recovery（L1236-1271）

現有 startup recovery 邏輯：
- 啟動時掃描所有 `status="running"` 的卡片
- 有 `on_success_action` 的卡片：補做流轉（move_to 目標 list）
- 無流轉動作的卡片：直接標記為 `completed`

**與 Watchdog 的互動設計**：
- Watchdog 運行在 worker 主迴圈**之內**（非獨立進程），因此 worker 重啟時 Watchdog 也會重啟
- startup recovery 在 Watchdog 啟動**之前**執行，先清理 stale cards
- Watchdog 初始化時應清空所有重試計數器（上次的 SUSPECTED 狀態不延續）
- **建議**：startup recovery 增加一個 log 標記 `recovered_by=startup`，與 Watchdog 的 `recovered_by=watchdog` 區分

```python
# Watchdog 啟動時的初始化
class WatchdogState:
    def __init__(self):
        self.retry_counts: dict[int, int] = {}   # card_id → retry count
        self.last_heartbeat: dict[int, float] = {}  # card_id → last seen timestamp
        self.cooldown_until: dict[int, float] = {}   # card_id → cooldown expiry

    def reset(self):
        """worker startup 時呼叫，清空所有狀態"""
        self.retry_counts.clear()
        self.last_heartbeat.clear()
        self.cooldown_until.clear()
```

### 4.5 session_pool cleanup_loop

`ProcessPool._cleanup_loop()` 每 60 秒執行一次：
- 清理 TTL 過期的進程（`PROCESS_TTL = 1800s` / 30 分鐘無活動）
- 清理已退出的進程（`proc.poll() is not None`）

**Watchdog 與 cleanup_loop 的邊界**：

| 情境 | 負責者 | 原因 |
|------|--------|------|
| 進程正常完成後閒置超過 TTL | cleanup_loop | 正常生命週期管理 |
| 進程意外退出（crash） | cleanup_loop | `proc.poll() is not None` 偵測 |
| 進程存活但卡死（無輸出） | **Watchdog** | cleanup_loop 無法偵測（進程仍活） |
| 進程存活且正常工作 | 無需介入 | — |

**關鍵原則**：Watchdog **不應**直接操作 `ProcessPool._entries`，而是透過 `ProcessPool.kill(chat_key)` 公開介面終止進程，讓 cleanup_loop 維持自有的生命週期管理。

---

## 附錄：建議實作順序

1. **新增 `backend/app/core/watchdog.py`**：`WatchdogState` + 取樣邏輯
2. **擴充 heartbeat 查詢介面**：讓 Watchdog 能讀取各 card 的最後心跳時間
3. **嵌入 worker 主迴圈**：每 N 次迴圈（12s / 3s ≈ 每 4 次）執行一次 Watchdog check
4. **實作 fallback 與通知**：broadcast + WebSocket alert
5. **整合測試**：模擬進程卡死場景，驗證重啟與 fallback 流程
