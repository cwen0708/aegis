# Runner vs Worker 架構對照

> 更新：2026-03-25（Executor 重構後）

## 總覽

```
                          ┌─────────────────────────────┐
                          │      executor/ (共用層)       │
                          │  providers · auth · context  │
                          │  config_md · emitter · hb    │
                          └──────────┬──────────────────┘
                   ┌─────────────────┼─────────────────┐
                   ▼                                    ▼
          ┌─────────────────┐                 ┌─────────────────┐
          │   Runner 路徑    │                 │   Worker 路徑    │
          │  即時對話（Bot）  │                 │  卡片任務（排程） │
          └────────┬────────┘                 └────────┬────────┘
                   │                                    │
    chat_handler → runner → ProcessPool    worker → PTY/subprocess
          │                                        │
    PlatformTarget                          WebSocketTarget
    (Telegram edit)                        + OneStackTarget
```

AEGIS 有兩條 AI 執行路徑，透過 `executor/` 共用模組統一管理成員、認證、設定檔、串流。

---

## 對照表

| 項目 | **Runner**（即時對話） | **Worker**（卡片任務） |
|---|---|---|
| **觸發** | Telegram/LINE bot 訊息 | 卡片 pending（排程/手動/OneStack） |
| **進程** | `node cli.js` 持久（stdin 不 close，30min TTL） | `claude` CLI 一次性（stdin → close → wait） |
| **PTY** | 無（stdout pipe） | 有（winpty / ptyprocess） |
| **冷啟** | 首次 ~5s，後續零冷啟 | 每次 ~3-8s |
| **上下文** | 進程內建保留（同 session） | 無（每次新進程） |
| **工作目錄** | chat-workspace（持久，symlink） | task-workspace（臨時，複製，完成即刪） |
| **設定檔** | `build_config_md("chat")` → CLAUDE.md | `build_config_md("task")` → CLAUDE.md/Gemini.md |
| **Skills** | symlink → 原檔（即時生效） | 複製進 workspace |
| **MCP** | `.mcp.json` symlink | `.mcp.json` 複製 或 `--mcp-config` |
| **Prompt** | 純用戶訊息（soul/skills 由 CLAUDE.md 提供） | 卡片 content + dialogue hint |
| **歷史** | CLI session 內建保留 | 無 / aegis_stream 5 輪重組 |
| **串流** | `StreamEmitter` → `PlatformTarget`（edit placeholder） | `StreamEmitter` → `WebSocketTarget` + `OneStackTarget` |
| **結果** | Telegram 新訊息 → 刪 placeholder | 卡片 status / channel-send / aegis_stream |
| **認證** | `inject_auth_env()` / `inject_auth_to_os_environ()` | `inject_auth_env()` → env dict |
| **成員解析** | `resolve_member_for_chat(member_id)` | `resolve_member_for_task(stage_list_id)` |
| **超時** | ProcessPool TTL 30 分鐘 | 卡片 30 分 / chat 10 分 |
| **並行** | per-chat_key 一進程，lock 防並發 | workstation 上限 3 個 |
| **模型** | `ctx.effective_model("chat")` — 成員設定 → haiku | `ctx.effective_model("task")` — 成員設定 → sonnet |
| **Git** | 無 | `_git_commit_changes` |
| **心跳** | 無（ProcessPool TTL 管理） | `heartbeat_monitor` context manager |
| **適用** | 快問快答、資訊查詢 | 開發、部署、巡檢、排程 |

---

## 執行流程

### Runner 路徑

```
Telegram/LINE 訊息
  → handle_chat()
    → resolve_member_for_chat()       ← MemberContext（帳號+soul+MCP 一次查完）
    → ensure_chat_workspace()          ← CLAUDE.md + skills symlink + .mcp.json symlink
    → StreamEmitter([PlatformTarget])  ← 建立串流
    → run_ai_task(on_stream=emitter.emit_raw, use_process_pool=True, cwd=ws_path)
      → process_pool.send_message()
        → node cli.js stdin.write(msg)  ← 不 close
        → _read_until_result()          ← on_line → emitter → edit placeholder
    → 發送 Telegram 新訊息
    → 刪除 placeholder
```

### Worker 路徑

```
卡片 status=pending
  → process_pending_cards()（每 3 秒）
    → resolve_member_for_task()        ← MemberContext（三層路由：列表→專案→無）
    → _execute_card_task()（thread）
      → prepare_workspace()            ← CLAUDE.md + skills 複製 + .mcp.json
      → StreamEmitter([WebSocketTarget, OneStackTarget])
      → run_task(emitter=...)
        → heartbeat_monitor(emitter)   ← 背景心跳
        → PTY / subprocess 讀取迴圈
          → emitter.emit_raw()         ← stream-json → 解析 → 分發到所有 target
      → _apply_stage_action()          ← 移動/刪除卡片
      → cleanup_workspace()
```

---

## 串流三層架構（emitter.py）

```
Layer 1: StreamEmitter             入口，接收 raw stream-json
    ↓ emit_raw(line)
Layer 2: parse_stream_event()      解析為 StreamEvent（tool_call/text/result/...）
    ↓ StreamEvent
Layer 3: StreamTarget.handle()     輸出到目標（可組合）
    ├── WebSocketTarget            → BroadcastLog DB + HTTP → WS → 前端 Kanban
    ├── PlatformTarget             → Telegram/LINE placeholder 編輯（3s 節流）
    ├── OneStackTarget             → aegis_stream Supabase Realtime（2s 節流）
    └── NullTarget                 → 靜默（email/test）
```

新增輸出目標只需實作 `StreamTarget.handle(event)`。
Chat 也能推前端 Kanban（加 `WebSocketTarget`），Worker 也能推 Telegram（加 `PlatformTarget`）。

---

## 目錄結構

### Chat Workspace（持久）

```
.aegis/chat-workspaces/{member_slug}/{platform}:{chat_id}:{member_slug}/
├── CLAUDE.md                  ← build_config_md("chat")
├── .claude/
│   ├── settings.json          ← trust + skipDangerous
│   └── skills/
│       ├── shared_*.md        ← symlink → shared/skills/
│       └── *.md               ← symlink → members/{slug}/skills/
└── .mcp.json                  ← symlink → members/{slug}/mcp.json
```

### Task Workspace（臨時）

```
.aegis/workspaces/task-{card_id}/
├── CLAUDE.md                  ← build_config_md("task") — 或 Gemini.md 等
├── .claude/skills/            ← 複製（非 symlink）
├── .mcp.json                  ← 複製
├── .gitconfig                 ← GitHub PAT（如有）
└── {project_files}            ← symlink → 專案目錄
```

---

## 相關檔案

### Executor（統一共用模組）

| 檔案 | 職責 |
|------|------|
| `executor/__init__.py` | re-export |
| `executor/providers.py` | `PROVIDERS` + `build_command(mode="task"\|"chat")` |
| `executor/auth.py` | `inject_auth_env()` + `get_mcp_config_path()` / `_by_slug()` |
| `executor/context.py` | `MemberContext` + `resolve_member_for_task/chat()` |
| `executor/config_md.py` | `build_config_md()` + `PROVIDER_CONFIG` + `get_config_filename()` |
| `executor/emitter.py` | `StreamEmitter` + `StreamEvent` + 4 種 Target + `clean_ansi()` |
| `executor/heartbeat.py` | `heartbeat_monitor` context manager |

### Runner 路徑

| 檔案 | 職責 |
|------|------|
| `channels/chat_handler.py` | 入口：驗證→MemberContext→workspace→emitter→AI→回應 |
| `core/runner.py` | `run_ai_task()`：ProcessPool 分流 / CLI fallback |
| `core/session_pool.py` | ProcessPool：node cli.js 持久進程管理 |
| `core/chat_workspace.py` | chat workspace 建立/更新（symlink） |

### Worker 路徑

| 檔案 | 職責 |
|------|------|
| `worker.py` | 主程式：輪詢→MemberContext→emitter→PTY/subprocess→stage action |
| `core/task_workspace.py` | task workspace 建立/清理（複製） |

### 共用基建

| 檔案 | 職責 |
|------|------|
| `core/stream_parsers.py` | stream-json 解析（`parse_tool_call` / `parse_stream_json_text`） |
| `core/member_profile.py` | 成員目錄管理（soul / skills / mcp / memory） |
| `core/sandbox.py` | 環境白名單 + 進程隔離 |
