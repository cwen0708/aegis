---
name: AEGIS Process Pool 實作記錄
description: Claude CLI stdin pipe 持久進程池的踩坑過程、最終方案、Runner vs Worker 架構差異
type: project
---

# Process Pool 實作記錄（2026-03-25）

## 目標

Chat 路徑（Telegram/LINE bot 對話）保持 Claude CLI 進程活著，30 分鐘無活動才 kill。
第二條訊息零冷啟，上下文自動保留。

## 踩過的坑

### 坑 1：`--input-format stream-json` + `-p` 不相容

**嘗試**：`claude -p --input-format stream-json --output-format stream-json`
**結果**：BrokenPipe — `-p`（print 模式）是一次性的，stdin EOF 就退出，不支援多輪。
**結論**：`-p` 和 `--input-format stream-json` 互斥。

### 坑 2：`subprocess.Popen` 無 TTY → Claude CLI 不輸出

**嘗試**：直接 `subprocess.Popen(["claude", "--input-format", "stream-json", ...], stdin=PIPE, stdout=PIPE)`
**結果**：stdout 0 bytes。進程活著但不輸出。
**原因**：`claude` 命令（shell wrapper）偵測 stdin 不是 TTY，進入互動模式但不產生 stream-json 輸出。
**驗證**：從 SSH 終端（有 TTY）跑相同命令 → 成功。

### 坑 3：`ptyprocess` 模擬 TTY → 進入 TUI

**嘗試**：用 `PtyProcess.spawn(["claude", ...])` 提供假 TTY。
**結果**：Claude CLI 偵測到 TTY → 進入互動 TUI 模式（顯示 `╭───Claude Code v2.1.74───╮`），不是 stream-json。
**結論**：有 TTY = 互動 UI、沒 TTY = 不輸出。兩邊都不對。

### 坑 4：`script -qfc` 包裝 → Trust Dialog 阻擋

**嘗試**：`script -qfc "claude --input-format stream-json ..." /dev/null` 提供假 TTY。
**結果**：出現兩個信任確認對話框（workspace trust + bypass permissions），需要手動按鍵確認。
即使 `~/.claude/settings.json` 有 `trust_all_projects: true`，互動模式下仍然顯示。
**結論**：`script` 包裝走不通，TTY 模式不可避免地觸發 TUI。

### 坑 5：`env=` 參數導致 node cli.js 不輸出

**嘗試**：`subprocess.Popen(cmd, env=custom_env)` 傳自訂環境變數。
**結果**：即使 `custom_env = dict(os.environ)` 完整複製，node cli.js 也不輸出任何東西。
不傳 `env=`（繼承 os.environ）就正常。
**原因**：不明，但已驗證。可能是 Node.js 或 Claude CLI 內部對環境物件的某種檢查。
**解法**：永遠不傳 `env=`，auth/extra_env 透過臨時設定 `os.environ` 注入再清理。

### 坑 6：systemd 環境精簡 → 缺 HOME

**嘗試**：在 systemd service（uvicorn）裡 spawn 進程。
**結果**：`os.environ` 只有 `HOME, PATH, USER, LANG` 等基本變數，沒有 SSH session 的完整環境。
**解法**：systemd unit 有設定 `User=cwen0708`，`HOME` 自動帶上。其他變數不影響。

### 坑 7：`_read_init` 在 stdin 寫入前就讀 stdout → 永遠阻塞

**嘗試**：spawn 後先 `_read_init()` 讀 system/init 行，再送 user message。
**結果**：`readline()` 永遠阻塞 — Claude CLI 在 `--input-format stream-json` 模式下，需要**先收到第一條 user message 才會初始化並輸出 system init 行**。
**驗證**：`echo '{"type":"user",...}' | node cli.js ...` 有輸出，`Popen` 後不寫 stdin 就沒輸出。
**解法**：移除 `_read_init()`，第一次 `_send_and_read()` 時帶 `expect_init=True` 一起處理。

### 坑 8：`start_new_session=True` 導致進程行為異常

**嘗試**：Popen 加 `start_new_session=True`（Linux process group 隔離）。
**結果**：node cli.js 不輸出。
**解法**：移除 `start_new_session`。

## 最終成功方案

### 關鍵發現：`node cli.js` 繞過 shell wrapper

Happy Code 的做法：不執行 `claude` 命令，而是直接 `node /path/to/cli.js`。
這樣繞過了 shell wrapper 的 TTY 偵測和 TUI 啟動邏輯。

**路徑**：`/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js`

### 成功命令

```python
cmd = ["node", "--no-warnings", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js",
       "--input-format", "stream-json",
       "--output-format", "stream-json",
       "--verbose",
       "--dangerously-skip-permissions",
       "--model", "haiku"]

proc = subprocess.Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
# 不傳 env=（繼承環境）、不傳 start_new_session

# 送訊息
msg = {"type": "user", "message": {"role": "user", "content": "hello"}}
proc.stdin.write((json.dumps(msg) + "\n").encode())
proc.stdin.flush()  # 不 close！

# 讀回應（逐行 readline 直到 type=result）
for line in proc.stdout:
    data = json.loads(line)
    if data["type"] == "system":  # init 行
    if data["type"] == "assistant":  # 回應文字
    if data["type"] == "result":  # 本輪完成，break
```

### 多輪驗證

```
msg1: "Remember 42. Say OK." → [INIT] → [REPLY] OK. → [RESULT]
msg2: "What number?" → [INIT] → [REPLY] 42. → [RESULT]  ← 上下文保留
```

每輪都有獨立的 system/init 行和 result 行。進程不退出，stdin 持續可寫。

## 架構：ProcessPool（session_pool.py）

```
ProcessPool
├── _entries: dict[chat_key → ProcessEntry]
│   ProcessEntry = { proc, chat_key, model, session_id, last_active, lock }
├── send_message(chat_key, message, model, member_id, auth_info, extra_env, on_line)
│   → _get_or_spawn() → _send_and_read() → _read_until_result()
├── _spawn()
│   → node cli.js --input-format stream-json（不傳 env=、不 read_init）
├── _send_and_read()
│   → stdin.write(user_msg) → _read_until_result(expect_init=首次)
├── _read_until_result()
│   → readline loop: system → assistant → result → return
├── _cleanup_loop()
│   → 每 60 秒檢查 TTL 過期（30 分鐘）或進程死亡 → kill
└── kill(chat_key)
    → 手動清除
```

## Runner vs Worker 差異

| | Runner（chat_handler → ProcessPool） | Worker（卡片 → 一次性 subprocess） |
|---|---|---|
| 進程 | node cli.js 持久 | claude CLI 一次性 |
| 冷啟 | 首次 ~5s，後續零 | 每次 ~3-8s |
| 上下文 | 進程內建 | prompt 重組 |
| PTY | 無 | 有 |
| 即時串流 | on_line → Telegram placeholder | broadcast_log → WebSocket |
| soul/skills | `_build_chat_prompt()` 組裝 | CLAUDE.md + skills 目錄 |
| 適用 | 輕量對話 | 複雜任務（開發、部署、巡檢） |

## 重要注意事項

1. **不能傳 `env=` 給 Popen**：傳了 node cli.js 就不輸出，原因不明
2. **不能用 `start_new_session=True`**：同上
3. **第一條訊息前不能讀 stdout**：`--input-format stream-json` 要先收到 user message 才初始化
4. **每輪回應都有 system/init 行**：`_read_until_result` 要處理
5. **auth 注入用臨時 os.environ**：寫入 → spawn → 清理（不 thread-safe，但 spawn 有 pool_lock）
6. **cli.js 路徑**：`/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js`（從 `which claude` 反推）
