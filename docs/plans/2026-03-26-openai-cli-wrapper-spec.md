# OpenAI CLI Wrapper Spec — `scripts/openai_chat.py`

> 方案 B：subprocess CLI wrapper
> 作者：小良（技術主管）
> 日期：2026-03-26
> 實作者：小茵

---

## 1. 概述

`scripts/openai_chat.py` 作為 OpenAI API 的 subprocess CLI 包裝器，由 `runner.py` / `worker.py` 透過 `build_command()` 呼叫。職責單一：接收 prompt → 呼叫 OpenAI API → 輸出 JSON 結果。

所有認證、環境變數注入、重試邏輯皆由呼叫端（Python 層）處理，CLI 本身僅負責「執行一次 API 呼叫並回報結果或錯誤」。

---

## 2. 命令列介面

```bash
python scripts/openai_chat.py [OPTIONS]
```

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `--model MODEL` | 模型名稱 | `gpt-4o` |
| `-p, --prompt TEXT` | Prompt 文字（省略時從 stdin 讀取） | — |
| `--max-tokens N` | 最大 completion tokens | 不設限（API 預設） |
| `--temperature T` | 溫度 0~2 | `1.0` |
| `--system TEXT` | System prompt（可選） | — |

---

## 3. stdin / stdout 格式

### 3.1 輸入（stdin）

當 `-p` 未提供時，從 stdin 讀取直到 EOF，編碼為 **UTF-8**。

```bash
# 方式一：-p 參數
python scripts/openai_chat.py --model gpt-4o -p "Hello"

# 方式二：stdin
echo "Hello" | python scripts/openai_chat.py --model gpt-4o

# 方式三：subprocess.Popen stdin pipe（呼叫端使用）
proc.stdin.write(prompt.encode("utf-8"))
proc.stdin.close()
```

### 3.2 成功輸出（stdout，exit code 0）

單一 JSON 物件，一行輸出，結尾含換行：

```json
{
  "result_text": "助理的回覆文字",
  "model": "gpt-4o",
  "duration_ms": 1234,
  "cost_usd": 0.00123,
  "input_tokens": 150,
  "output_tokens": 75,
  "total_tokens": 225
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `result_text` | `string` | 模型回覆文字（必填） |
| `model` | `string` | 實際使用的模型 ID（必填） |
| `duration_ms` | `int` | API 呼叫耗時毫秒（必填） |
| `cost_usd` | `float` | 預估費用美元（best effort，無法算時填 `0.0`） |
| `input_tokens` | `int` | 輸入 token 數（必填） |
| `output_tokens` | `int` | 輸出 token 數（必填） |
| `total_tokens` | `int` | 總 token 數（必填） |

### 3.3 錯誤輸出（stderr）

錯誤時 **stdout 不輸出任何內容**，錯誤 JSON 寫入 **stderr**：

```json
{
  "error": "人類可讀的錯誤訊息",
  "error_code": "機器可讀的錯誤碼",
  "retry_after_seconds": 60
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `error` | `string` | 人類可讀錯誤訊息（必填） |
| `error_code` | `string` | 錯誤碼，見 §4（必填） |
| `retry_after_seconds` | `int?` | 建議重試秒數（僅 rate_limit 時提供） |

---

## 4. Exit Code 規範

| Exit Code | error_code | 情境 | 呼叫端行為 |
|-----------|------------|------|------------|
| `0` | — | 成功 | 解析 stdout JSON |
| `1` | `auth_missing` | `OPENAI_API_KEY` 未設定 | fallback 帳號或終止 |
| `2` | `auth_invalid` | API 回傳 401 Unauthorized | fallback 帳號或終止 |
| `3` | `rate_limit` | API 回傳 429 Rate Limit | 依 `retry_after_seconds` 重試 |
| `4` | `model_not_found` | API 回傳 404 / model 不存在 | 終止（fatal） |
| `5` | `invalid_request` | 400 Bad Request（prompt 太長等） | 終止（fatal） |
| `6` | `api_error` | 500~599 / timeout / 網路錯誤 | 可重試（transient） |
| `7` | `missing_dependency` | `openai` 套件未安裝 | 終止（fatal） |
| `9` | `unknown` | 未預期例外 | 記錄 log 後終止 |

### 設計原則

- **Exit code 1~2**：認證類 → 呼叫端可嘗試 fallback 帳號
- **Exit code 3**：限流 → 呼叫端負責退避重試
- **Exit code 4~5**：請求本身有問題 → 不重試
- **Exit code 6**：暫時性錯誤 → 可重試
- **Exit code 7, 9**：環境 / 未知錯誤 → 終止

---

## 5. 環境變數與 Key 優先順序

### 5.1 取 Key 流程（呼叫端負責）

```
Credential Vault (DB: SystemSetting / MemberCredential)
        ↓ 找到 → inject 到 env dict
        ↓ 沒找到
環境變數 fallback (os.environ["OPENAI_API_KEY"])
        ↓ 都沒有
CLI 收到空值 → exit 1 (auth_missing)
```

**重要**：CLI 本身 **不查詢** Credential Vault，只從 `os.environ` 取值。
優先順序由呼叫端的 `EnvironmentBuilder` chain 保證：

```python
env = (EnvironmentBuilder()
    .with_system_keys()           # ← 全域 API keys (SystemSetting)
    .with_project_vars(project_id) # ← 專案級變數
    .with_auth("openai", auth_info) # ← Credential Vault 注入
    .build())
# 後寫入的 key 覆蓋先寫入的 → auth_info 優先
```

### 5.2 CLI 讀取的環境變數

| 變數 | 用途 | 必要 |
|------|------|------|
| `OPENAI_API_KEY` | API 認證 | **必要** |
| `OPENAI_BASE_URL` | 自訂 API endpoint（相容 Azure 等） | 選填 |
| `OPENAI_ORG_ID` | Organization ID | 選填 |

### 5.3 inject_auth_env() 整合

`executor/auth.py` 中的 `inject_auth_env()` 對 openai provider：

```python
def inject_auth_env(env: dict, provider: str, auth_info: dict):
    if provider == "openai":
        if auth_info.get("api_key"):
            env["OPENAI_API_KEY"] = auth_info["api_key"]
        if auth_info.get("base_url"):
            env["OPENAI_BASE_URL"] = auth_info["base_url"]
        if auth_info.get("org_id"):
            env["OPENAI_ORG_ID"] = auth_info["org_id"]
```

---

## 6. 與 build_command() 的整合

### 6.1 providers.py 設定

```python
PROVIDERS = {
    "openai": {
        "cmd_base": ["python", "scripts/openai_chat.py"],
        "json_output": True,
        "default_model": "gpt-4o",
        "stdin_prompt": True,   # ← 新增：prompt 走 stdin
    },
}
```

### 6.2 build_command() 邏輯

```python
def build_command(provider: str, prompt: str, model: str = "",
                  mode: str = "chat", **kwargs) -> tuple[list[str], bool]:
    config = PROVIDERS[provider]
    cmd = list(config["cmd_base"])

    resolved_model = model or config.get("default_model", "gpt-4o")
    cmd.extend(["--model", resolved_model])

    # system prompt 由呼叫端決定是否帶入
    if kwargs.get("system_prompt"):
        cmd.extend(["--system", kwargs["system_prompt"]])

    if kwargs.get("max_tokens"):
        cmd.extend(["--max-tokens", str(kwargs["max_tokens"])])

    # prompt 走 stdin（避免 shell 特殊字元問題）
    stdin_prompt = config.get("stdin_prompt", False)

    return cmd, stdin_prompt
```

### 6.3 呼叫端整合（worker.py / runner.py）

```python
cmd, use_stdin = build_command(
    provider="openai",
    prompt=prompt,
    model=model_override,
    mode="task",
)

proc = subprocess.Popen(
    cmd,
    cwd=project_path,
    stdin=subprocess.PIPE if use_stdin else None,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,   # ← 分離 stderr（解析錯誤 JSON）
    env=env,
)

if use_stdin and proc.stdin:
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()

stdout_data, stderr_data = proc.communicate(timeout=300)
exit_code = proc.returncode
```

### 6.4 結果解析

```python
if exit_code == 0:
    token_info = parse_openai_json(stdout_data.decode("utf-8"))
    result_text = token_info["result_text"]
else:
    error_info = json.loads(stderr_data.decode("utf-8"))
    error_code = error_info.get("error_code", "unknown")
    # 依 exit_code 決定 retry / fallback / abort
    if exit_code in (1, 2):    # auth 問題 → fallback
        ...
    elif exit_code == 3:        # rate limit → backoff
        retry_after = error_info.get("retry_after_seconds", 30)
        ...
    elif exit_code == 6:        # transient → retry
        ...
    else:                       # fatal → abort
        ...
```

---

## 7. 錯誤處理對照表

| OpenAI API 回應 | HTTP Status | error_code | Exit Code |
|-----------------|-------------|------------|-----------|
| — | — (key 未設定) | `auth_missing` | `1` |
| Incorrect API key | 401 | `auth_invalid` | `2` |
| Rate limit exceeded | 429 | `rate_limit` | `3` |
| Model not found | 404 | `model_not_found` | `4` |
| Max tokens exceeded | 400 | `invalid_request` | `5` |
| Invalid prompt | 400 | `invalid_request` | `5` |
| Internal server error | 500 | `api_error` | `6` |
| Timeout | — | `api_error` | `6` |
| Connection error | — | `api_error` | `6` |
| `import openai` fails | — | `missing_dependency` | `7` |
| 其他例外 | — | `unknown` | `9` |

---

## 8. 實作注意事項

1. **stderr 與 stdout 分離**：成功時只寫 stdout，失敗時只寫 stderr。呼叫端目前用 `stderr=subprocess.STDOUT` 合併輸出，需改為 `stderr=subprocess.PIPE` 分離。

2. **Timeout**：CLI 本身不設 timeout，由呼叫端 `proc.communicate(timeout=N)` 控制。若 API 呼叫卡住，呼叫端負責 kill process。

3. **cost_usd 計算**：可內建 token pricing 表，若無法計算填 `0.0`。未來可從外部 config 載入最新價格。

4. **Streaming**：本版不支援 streaming。若未來需要，改為逐行輸出 JSON Lines（`{"type":"delta","text":"..."}` / `{"type":"result",...}`），但這是 v2 範疇。

5. **多輪對話**：本版僅支援單輪。多輪由呼叫端拼接 history 為單一 prompt 或未來以 `--messages-file` 傳入 JSON。

---

## 9. 與現有 parse_openai_json() 的相容性

`stream_parsers.py` 中的 `parse_openai_json()` 已支援目前的輸出格式，新 spec 完全向後相容。只需確保：
- 成功時 stdout 為合法 JSON
- 包含 `result_text`, `model`, `duration_ms`, `input_tokens`, `output_tokens` 欄位

---

## 10. Checklist（小茵實作用）

- [ ] 重構 exit code：目前統一 `sys.exit(1)` → 改為分級 exit code
- [ ] 捕捉 `openai.AuthenticationError` → exit 2
- [ ] 捕捉 `openai.RateLimitError` → exit 3，解析 retry-after header
- [ ] 捕捉 `openai.NotFoundError` → exit 4
- [ ] 捕捉 `openai.BadRequestError` → exit 5
- [ ] 捕捉 `openai.APIStatusError` (5xx) → exit 6
- [ ] 捕捉 `openai.APIConnectionError` / `openai.APITimeoutError` → exit 6
- [ ] 錯誤 JSON 寫 stderr，成功 JSON 寫 stdout
- [ ] 支援 `--system`、`--max-tokens`、`--temperature` 參數
- [ ] 支援 `OPENAI_BASE_URL`、`OPENAI_ORG_ID` 環境變數
- [ ] 呼叫端 `stderr=subprocess.PIPE` 分離（runner.py + worker.py）
- [ ] 呼叫端 exit code 分流處理（retry / fallback / abort）
- [ ] `providers.py` 加入 `"stdin_prompt": True`
