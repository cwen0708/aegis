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
    """更新工作台數量（從 Settings 呼叫）"""
    global MAX_WORKSTATIONS, workstation_semaphore
    if new_max < 1:
        new_max = 1
    MAX_WORKSTATIONS = new_max
    workstation_semaphore = asyncio.Semaphore(new_max)
    logger.info(f"[Runner] MAX_WORKSTATIONS updated to {new_max}")

# 追蹤忙碌的成員（同一成員同時只能佔用一個工作台）
busy_members: set[int] = set()

# 模組級全域：追蹤運行中的任務，供 WebSocket 廣播 + abort
# key: card_id, value: { task_id, project, card_title, started_at, pid, process, member_id }
running_tasks: Dict[int, Dict[str, Any]] = {}

# 階段到提供者的預設路由表 (Agent Routing)
PHASE_ROUTING = {
    "PLANNING": "gemini",
    "REVIEWING": "gemini",
    "DEVELOPING": "claude",
    "VERIFYING": "claude"
}

# 支援的 AI 提供者指令配置
PROVIDERS = {
    "gemini": {
        "cmd_base": [r"C:\Users\cwen0708\AppData\Roaming\npm\gemini.cmd"],
        "args": ["-p", "{prompt}", "-y", "--model", "gemini-2.5-flash"],
        "env": {}
    },
    "claude": {
        "cmd_base": ["claude"],
        "args": ["-p", "{prompt}", "--dangerously-skip-permissions", "--model", "opus", "--output-format", "json"],
        "env": {"CLAUDECODE": "1"}
    }
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


async def run_ai_task(task_id: int, project_path: str, prompt: str, phase: str, forced_provider: Optional[str] = None, card_title: str = "", project_name: str = "", member_id: Optional[int] = None) -> Dict[str, Any]:
    """
    執行單一 AI 任務，受 Semaphore 保護。
    使用 asyncio subprocess 支援即時 log streaming 和 abort。
    """
    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else PHASE_ROUTING.get(phase, "gemini")
    config = PROVIDERS[provider_name]

    cmd = list(config["cmd_base"])
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd.append(arg.replace("{prompt}", prompt))
        else:
            cmd.append(arg)

    env = os.environ.copy()
    env.update(config.get("env", {}))

    logger.info(f"[Task {task_id}] Waiting for workstation... (Phase: {phase}, Provider: {provider_name})")

    async with workstation_semaphore:
        logger.info(f"[Task {task_id}] Workstation acquired! Executing {provider_name} in {project_path}")
        if member_id:
            busy_members.add(member_id)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            # 註冊到 running_tasks
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

            # 逐行讀取 stdout，廣播 task_log
            output_lines = []
            try:
                async def read_stream():
                    while True:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=2400)
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace")
                        output_lines.append(text)
                        await broadcast_event("task_log", {"card_id": task_id, "line": text})

                await read_stream()
                await proc.wait()
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                running_tasks.pop(task_id, None)
                if member_id:
                    busy_members.discard(member_id)
                await broadcast_event("task_failed", {"card_id": task_id, "reason": "timeout"})
                _save_task_log(task_id, card_title, project_name, provider_name, member_id, "timeout", {})
                return {"status": "timeout", "output": "".join(output_lines), "provider": provider_name}

            output = "".join(output_lines)
            running_tasks.pop(task_id, None)
            if member_id:
                busy_members.discard(member_id)

            status = "success" if proc.returncode == 0 else "error"
            event = "task_completed" if status == "success" else "task_failed"
            await broadcast_event(event, {"card_id": task_id, "status": status})

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
            running_tasks.pop(task_id, None)
            if member_id:
                busy_members.discard(member_id)
            logger.exception(f"[Task {task_id}] Execution failed: {e}")
            from app.core.ws_manager import broadcast_event
            await broadcast_event("task_failed", {"card_id": task_id, "reason": str(e)})
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
