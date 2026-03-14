import asyncio
import subprocess
import os
import json
import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 全域工作台控制
# 預設值，會在啟動時從 DB 讀取 max_workstations setting
MAX_WORKSTATIONS = 3
workstation_semaphore = asyncio.Semaphore(MAX_WORKSTATIONS)


def update_max_workstations(new_max: int):
    """更新工作台數量（從 Settings 呼叫）。
    調整既有 semaphore 的內部計數而非替換物件，
    避免已持有引用的 coroutine 失去互斥保護。"""
    global MAX_WORKSTATIONS
    if new_max < 1:
        new_max = 1
    old_max = MAX_WORKSTATIONS
    MAX_WORKSTATIONS = new_max
    diff = new_max - old_max
    if diff > 0:
        for _ in range(diff):
            workstation_semaphore.release()
    elif diff < 0:
        workstation_semaphore._value = max(0, workstation_semaphore._value + diff)
    logger.info(f"[Runner] MAX_WORKSTATIONS updated to {new_max}")

# 追蹤忙碌的成員（同一成員同時只能佔用一個工作台）
busy_members: set[int] = set()

# 模組級全域：追蹤運行中的任務，供 WebSocket 廣播 + abort
# key: card_id, value: { task_id, project, card_title, started_at, pid, process, member_id }
running_tasks: Dict[int, Dict[str, Any]] = {}

# 支援的 AI 提供者指令配置
PROVIDERS = {
    "gemini": {
        "cmd_base": ["gemini"],
        "args": ["-p", "{prompt}", "-y", "--model", "gemini-2.5-flash"],
        "env": {},
        "json_output": False,
    },
    "claude": {
        "cmd_base": ["claude"],
        "args": ["-p", "{prompt}", "--dangerously-skip-permissions", "--model", "opus", "--output-format", "json"],
        "env": {},
        "json_output": True,
    },
    # TODO: Codex CLI 尚未驗證，需要 ChatGPT Plus/Pro 帳號登入
    "codex": {
        "cmd_base": ["codex"],
        "args": ["-p", "{prompt}"],  # 待確認完整參數
        "env": {},
        "json_output": False,  # 待確認是否支援 JSON 輸出
    },
    # Ollama 本地模型，model 會在執行時替換
    "ollama": {
        "cmd_base": ["ollama", "run"],
        "args": ["{model}"],  # model 由設定決定，預設 llama3.1:8b
        "env": {},
        "json_output": False,
        "default_model": "llama3.1:8b",
        "stdin_prompt": True,  # Ollama 用 stdin 傳 prompt
    },
}

def _parse_claude_json(output: str) -> Dict[str, Any]:
    """從 Claude CLI JSON 輸出解析 token 用量"""
    try:
        data = json.loads(output.strip())
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})
        # 取第一個模型的資訊
        model_name = ""
        model_info = {}
        if model_usage:
            model_name = list(model_usage.keys())[0]
            model_info = model_usage[model_name]
        return {
            "result_text": data.get("result", ""),
            "model": model_name,
            "duration_ms": data.get("duration_ms", 0),
            "cost_usd": data.get("total_cost_usd", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        }
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}


def _save_task_log(card_id: int, card_title: str, project_name: str, provider: str,
                   member_id: Optional[int], status: str, token_info: Dict[str, Any]):
    """儲存任務執行記錄到 TaskLog"""
    try:
        from app.database import engine
        from app.models.core import TaskLog
        from sqlmodel import Session
        with Session(engine) as session:
            log = TaskLog(
                card_id=card_id,
                card_title=card_title,
                project_name=project_name,
                provider=provider,
                model=token_info.get("model", ""),
                member_id=member_id,
                status=status,
                duration_ms=token_info.get("duration_ms", 0),
                input_tokens=token_info.get("input_tokens", 0),
                output_tokens=token_info.get("output_tokens", 0),
                cache_read_tokens=token_info.get("cache_read_tokens", 0),
                cache_creation_tokens=token_info.get("cache_creation_tokens", 0),
                cost_usd=token_info.get("cost_usd", 0),
            )
            session.add(log)
            session.commit()
    except Exception as e:
        logger.warning(f"[TaskLog] Failed to save: {e}")


async def run_ai_task(task_id: int, project_path: str, prompt: str, phase: str, forced_provider: Optional[str] = None, card_title: str = "", project_name: str = "", member_id: Optional[int] = None, model_override: Optional[str] = None, project_id: Optional[int] = None) -> Dict[str, Any]:
    """
    執行單一 AI 任務，受 Semaphore 保護。
    使用 asyncio subprocess 支援即時 log streaming 和 abort。
    """
    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else "claude"
    config = PROVIDERS[provider_name]

    # 決定模型（支援成員指定的 model）
    model = model_override or config.get("default_model", "")

    cmd = list(config["cmd_base"])
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd.append(arg.replace("{prompt}", prompt))
        elif "{model}" in arg:
            cmd.append(arg.replace("{model}", model))
        else:
            cmd.append(arg)

    # 如果有 model_override，替換 args 中的 --model 值（支援 claude/gemini）
    if model_override:
        for i, arg in enumerate(cmd):
            if arg == "--model" and i + 1 < len(cmd):
                cmd[i + 1] = model_override
                break

    # Ollama 等使用 stdin 傳 prompt 的 provider
    stdin_prompt = config.get("stdin_prompt", False)

    from app.core.sandbox import build_sanitized_env, get_popen_kwargs
    env = build_sanitized_env(project_id=project_id)
    env.update(config.get("env", {}))

    logger.info(f"[Task {task_id}] Waiting for workstation... (Phase: {phase}, Provider: {provider_name})")

    async with workstation_semaphore:
        logger.info(f"[Task {task_id}] Workstation acquired! Executing {provider_name} in {project_path}")
        if member_id:
            busy_members.add(member_id)

        try:
            # Ollama 等 provider 使用 stdin 傳 prompt
            popen_kwargs = get_popen_kwargs()
            proc = subprocess.Popen(
                cmd,
                cwd=project_path,
                stdin=subprocess.PIPE if stdin_prompt else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                **popen_kwargs,
            )
            # 如果使用 stdin，寫入 prompt 後關閉
            if stdin_prompt and proc.stdin:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()

            # 註冊到 running_tasks（task_id=0 是 chat 對話，不加入）
            if task_id != 0:
                running_tasks[task_id] = {
                    "task_id": task_id,
                    "project": project_name,
                    "card_title": card_title,
                    "started_at": time.time(),
                    "pid": proc.pid,
                    "process": proc,
                    "provider": provider_name,
                    "member_id": member_id,
                }

                # 通知 WebSocket
                from app.core.ws_manager import broadcast_event
                await broadcast_event("task_started", {
                    "card_id": task_id, "card_title": card_title,
                    "project": project_name, "provider": provider_name
                })

            # 在 thread 裡讀取 stdout，避免阻塞 event loop
            def _read_output():
                lines = []
                for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace")
                    lines.append(line)
                proc.wait()
                return lines

            try:
                output_lines = await asyncio.wait_for(
                    asyncio.to_thread(_read_output),
                    timeout=2400,
                )
            except asyncio.TimeoutError:
                proc.kill()
                proc.wait()
                if task_id != 0:
                    running_tasks.pop(task_id, None)
                if member_id:
                    busy_members.discard(member_id)
                _save_task_log(task_id, card_title, project_name, provider_name, member_id, "timeout", {})
                return {"status": "timeout", "output": "任務超時 (40 分鐘)", "provider": provider_name}

            output = "".join(output_lines)
            if task_id != 0:
                running_tasks.pop(task_id, None)
            if member_id:
                busy_members.discard(member_id)

            status = "success" if proc.returncode == 0 else "error"
            # 注意：不在此處廣播 task_completed/task_failed
            # 由 poller._execute_and_update 在更新完 CardIndex 後才廣播
            # 避免前端收到事件時 index 尚未更新的競態條件

            # 解析 token 用量並儲存 TaskLog
            token_info = {}
            actual_output = output
            if provider_name == "claude":
                token_info = _parse_claude_json(output)
                if token_info.get("result_text"):
                    actual_output = token_info["result_text"]

            _save_task_log(task_id, card_title, project_name, provider_name, member_id, status, token_info)

            return {
                "status": status,
                "output": actual_output,
                "provider": provider_name,
                "exit_code": proc.returncode,
                "token_info": token_info,
            }

        except Exception as e:
            if task_id != 0:
                running_tasks.pop(task_id, None)
            if member_id:
                busy_members.discard(member_id)
            logger.exception(f"[Task {task_id}] Execution failed: {e}")
            _save_task_log(task_id, card_title, project_name, provider_name, member_id, "error", {})
            return {"status": "error", "output": str(e), "provider": provider_name}


def abort_task(card_id: int) -> bool:
    """中止運行中的任務"""
    task = running_tasks.get(card_id)
    if not task:
        return False
    proc = task.get("process")
    if proc and proc.returncode is None:
        proc.kill()
        return True
    return False
