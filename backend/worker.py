"""
Aegis Worker - 獨立任務執行程序
獨立於 FastAPI 運行，負責：
1. 掃描 pending 卡片
2. 執行 AI CLI 任務
3. 即時輸出透過 HTTP 傳給 FastAPI 廣播
4. 更新卡片狀態
"""
import os
import sys

# 載入 .env 檔案（用於 CLAUDE_CODE_OAUTH_TOKEN 等環境變數）
from pathlib import Path
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().split("\n"):
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
import time
import json
import logging
import subprocess
import platform
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# 加入 app 路徑
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, select
from app.database import engine
from app.models.core import (
    Card, CardIndex, StageList, Project, SystemSetting,
    Member, MemberAccount, Account, TaskLog, CronLog, MemberDialogue
)
from app.core.card_file import CardData, read_card, write_card
from app.core.card_index import sync_card_to_index, remove_card_from_index
from app.core.telemetry import is_system_overloaded
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.memory_manager import write_member_short_term_memory

# HTTP client for broadcasting
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ==========================================
# 配置
# ==========================================
POLL_INTERVAL = 3  # 秒
API_BASE = "http://127.0.0.1:8899/api/v1"
MAX_WORKSTATIONS = 3  # 預設，啟動時從 DB 讀取

# AI Provider 配置（從 runner.py 移植）
PHASE_ROUTING = {
    "PLANNING": "gemini",
    "REVIEWING": "gemini",
    "DEVELOPING": "claude",
    "VERIFYING": "claude",
    "SCHEDULED": "claude",
    "ONESTACK": "claude",
}

PROVIDERS = {
    "gemini": {
        "cmd_base": ["gemini"],
        "args": ["-p", "{prompt}", "-y", "--model", "gemini-3.1-pro-preview"],
        "json_output": False,
    },
    "claude": {
        "cmd_base": ["claude"],
        # 使用 stream-json + verbose 實現即時串流輸出
        "args": ["-p", "{prompt}", "--dangerously-skip-permissions", "--model", "sonnet",
                 "--output-format", "stream-json", "--verbose"],
        "json_output": False,
        "stream_json": True,  # 標記需要解析 stream-json
    },
    "ollama": {
        "cmd_base": ["ollama", "run"],
        "args": ["{model}"],
        "json_output": False,
        "default_model": "llama3.1:8b",
        "stdin_prompt": True,
    },
}


# ==========================================
# HTTP 工具
# ==========================================
def broadcast_log(card_id: int, line: str):
    """透過 HTTP 發送 log 給 FastAPI 廣播"""
    try:
        # 過濾掉 ANSI escape codes 和控制字符
        import re
        clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
        clean_line = ''.join(c for c in clean_line if c.isprintable() or c in '\n\r\t')

        if not clean_line.strip():
            return  # 跳過空行

        logger.info(f"[Broadcast] card={card_id} len={len(clean_line)}")
        data = json.dumps({"card_id": card_id, "line": clean_line}).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/internal/broadcast-log",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"[Broadcast] Failed: {e}")
        pass


def broadcast_event(event_type: str, payload: dict):
    """透過 HTTP 發送事件給 FastAPI 廣播"""
    try:
        data = json.dumps({"event": event_type, "payload": payload}).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/internal/broadcast-event",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"[Broadcast] Failed to send {event_type}: {e}")


# ==========================================
# DB 查詢工具
# ==========================================
def get_max_workstations() -> int:
    """從 DB 讀取最大工作台數"""
    with Session(engine) as session:
        setting = session.get(SystemSetting, "max_workstations")
        if setting:
            try:
                return int(setting.value)
            except ValueError:
                pass
    return MAX_WORKSTATIONS


def is_worker_paused() -> bool:
    """檢查 Worker 是否被暫停"""
    with Session(engine) as session:
        setting = session.get(SystemSetting, "worker_paused")
        return setting and setting.value == "true"


def get_running_count() -> int:
    """取得目前運行中的任務數"""
    with Session(engine) as session:
        stmt = select(CardIndex).where(CardIndex.status == "running")
        return len(list(session.exec(stmt).all()))


def is_member_busy(member_id: int) -> bool:
    """檢查成員是否正在執行其他任務"""
    if not member_id:
        return False
    with Session(engine) as session:
        stmt = select(CardIndex).where(
            CardIndex.status == "running",
            CardIndex.member_id == member_id
        )
        return session.exec(stmt).first() is not None


def get_pending_cards() -> list:
    """取得待執行的卡片"""
    with Session(engine) as session:
        stmt = select(CardIndex).where(CardIndex.status == "pending")
        return list(session.exec(stmt).all())


def get_primary_provider(member_id: int) -> tuple:
    """從成員的主帳號取得 provider、model 和認證資訊
    回傳 (provider, model, auth_info)
    auth_info = {
        'auth_type': 'cli' | 'api_key',
        'oauth_token': str,  # CLI Token
        'api_key': str,      # API Key
    }
    """
    with Session(engine) as session:
        stmt = select(MemberAccount).where(
            MemberAccount.member_id == member_id
        ).order_by(MemberAccount.priority)
        binding = session.exec(stmt).first()
        if binding:
            account = session.get(Account, binding.account_id)
            if account:
                auth_info = {
                    'auth_type': getattr(account, 'auth_type', 'cli'),
                    'oauth_token': getattr(account, 'oauth_token', '') or '',
                    'api_key': getattr(account, 'api_key', '') or '',
                }
                return account.provider, binding.model or "", auth_info
    return None, "", {}


def resolve_member(stage_list_id: int, phase: str) -> tuple:
    """解析任務應該由哪個成員執行
    回傳 (member_id, provider, model, member_slug, auth_info)
    """
    with Session(engine) as session:
        # 1. 列表級指派
        stage_list = session.get(StageList, stage_list_id)
        if stage_list and stage_list.member_id:
            member = session.get(Member, stage_list.member_id)
            if member:
                provider, model, auth_info = get_primary_provider(member.id)
                logger.info(f"[Router] List '{stage_list.name}' → {member.name} ({provider}/{model})")
                return member.id, provider, model, member.slug, auth_info

        # 2. 專案預設成員（OneStack/Scheduled 等系統列表 fallback）
        if stage_list:
            project = session.get(Project, stage_list.project_id)
            if project and project.default_member_id:
                member = session.get(Member, project.default_member_id)
                if member:
                    provider, model, auth_info = get_primary_provider(member.id)
                    logger.info(f"[Router] Project '{project.name}' default → {member.name} ({provider}/{model})")
                    return member.id, provider, model, member.slug, auth_info

        # 3. 全域預設
        setting = session.get(SystemSetting, f"phase_routing.{phase}")
        if setting and setting.value:
            try:
                member = session.get(Member, int(setting.value))
                if member:
                    provider, model, auth_info = get_primary_provider(member.id)
                    return member.id, provider, model, member.slug, auth_info
            except (ValueError, TypeError):
                pass

        # 4. 無指派
        return None, None, "", None, {}


# ==========================================
# 卡片狀態更新
# ==========================================
def update_card_status(card_id: int, new_status: str, append_content: str = ""):
    """更新卡片狀態（MD 檔 + DB）"""
    with Session(engine) as session:
        idx = session.get(CardIndex, card_id)
        if not idx:
            return

        file_path = Path(idx.file_path)
        try:
            card_data = read_card(file_path)
            card_data.status = new_status
            if append_content:
                card_data.content += append_content
            write_card(file_path, card_data)
            sync_card_to_index(session, card_data, idx.project_id, str(file_path))
        except Exception as e:
            logger.error(f"[Card {card_id}] Failed to update MD: {e}")

        # Dual-write ORM
        orm_card = session.get(Card, card_id)
        if orm_card:
            orm_card.status = new_status
            if append_content:
                orm_card.content = (orm_card.content or "") + append_content
            session.add(orm_card)

        session.commit()


def mark_card_running(card_id: int, member_id: Optional[int]):
    """標記卡片為 running 並設定 member_id"""
    with Session(engine) as session:
        idx = session.get(CardIndex, card_id)
        if idx:
            idx.status = "running"
            idx.member_id = member_id
            session.add(idx)

            # 也更新 MD 檔
            file_path = Path(idx.file_path)
            try:
                card_data = read_card(file_path)
                card_data.status = "running"
                write_card(file_path, card_data)
            except Exception as e:
                logger.warning(f"[Card {card_id}] Failed to update MD to running: {e}")

        orm_card = session.get(Card, card_id)
        if orm_card:
            orm_card.status = "running"
            session.add(orm_card)

        session.commit()


# ==========================================
# JSON 解析
# ==========================================
def parse_claude_json(output: str) -> Dict[str, Any]:
    """從 Claude CLI JSON 輸出解析 token 用量"""
    try:
        data = json.loads(output.strip())
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})
        model_name = ""
        if model_usage:
            model_name = list(model_usage.keys())[0]
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


def save_task_log(card_id: int, card_title: str, project_name: str, provider: str,
                  member_id: Optional[int], status: str, token_info: Dict[str, Any]):
    """儲存任務執行記錄"""
    try:
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


def save_cron_log(cron_job_id: int, cron_job_name: str, card_id: int, card_title: str,
                  project_id: int, project_name: str, provider: str,
                  member_id: Optional[int], status: str, output: str,
                  error_message: str, prompt_snapshot: str, token_info: Dict[str, Any]):
    """儲存排程執行記錄到 CronLog"""
    try:
        with Session(engine) as session:
            log = CronLog(
                cron_job_id=cron_job_id,
                cron_job_name=cron_job_name,
                card_id=card_id,
                card_title=card_title,
                project_id=project_id,
                project_name=project_name,
                provider=provider,
                model=token_info.get("model", ""),
                member_id=member_id,
                status=status,
                output=output,
                error_message=error_message,
                prompt_snapshot=prompt_snapshot,
                duration_ms=token_info.get("duration_ms", 0),
                input_tokens=token_info.get("input_tokens", 0),
                output_tokens=token_info.get("output_tokens", 0),
                cache_read_tokens=token_info.get("cache_read_tokens", 0),
                cache_creation_tokens=token_info.get("cache_creation_tokens", 0),
                cost_usd=token_info.get("cost_usd", 0),
            )
            session.add(log)
            session.commit()
            logger.info(f"[CronLog] Saved log for cron_job {cron_job_id}, status={status}")
    except Exception as e:
        logger.warning(f"[CronLog] Failed to save: {e}")


def delete_card_completely(card_id: int):
    """完全刪除卡片（MD 檔 + CardIndex + Card ORM）"""
    try:
        with Session(engine) as session:
            idx = session.get(CardIndex, card_id)
            if idx and idx.file_path:
                md_path = Path(idx.file_path)
                if md_path.exists():
                    md_path.unlink()
                remove_card_from_index(session, card_id)

            orm_card = session.get(Card, card_id)
            if orm_card:
                session.delete(orm_card)

            session.commit()
        logger.info(f"[Worker] Card {card_id} deleted completely")
    except Exception as e:
        logger.warning(f"[Worker] Failed to delete card {card_id}: {e}")


def _parse_cron_job_id(title: str) -> Optional[int]:
    """從卡片標題解析 cron_job_id，如 '[cron_43] xxx' -> 43"""
    import re
    m = re.match(r'\[cron_(\d+)\]', title)
    return int(m.group(1)) if m else None


def _extract_dialogue(output: str) -> Optional[str]:
    """從 AI 輸出中解析 <!-- dialogue: xxx --> 標記"""
    import re
    m = re.search(r'<!--\s*dialogue:\s*(.+?)\s*-->', output)
    return m.group(1).strip() if m else None


def _save_member_dialogue(member_id: int, card_id: int, card_title: str,
                          project_name: str, dialogue_type: str, text: str):
    """儲存成員對話到 DB 並透過 WebSocket 推送"""
    try:
        with Session(engine) as session:
            d = MemberDialogue(
                member_id=member_id,
                card_id=card_id,
                card_title=card_title,
                project_name=project_name,
                dialogue_type=dialogue_type,
                text=text,
                status="success" if dialogue_type == "task_complete" else "error",
            )
            session.add(d)
            session.commit()
        broadcast_event("member_dialogue", {
            "member_id": member_id,
            "text": text,
            "dialogue_type": dialogue_type,
            "card_title": card_title,
        })
        logger.info(f"[Dialogue] {dialogue_type}: {text[:40]}")
    except Exception as e:
        logger.warning(f"[Dialogue] Failed to save: {e}")


# ==========================================
# 任務執行（PTY 模式，即時串流輸出）
# ==========================================
def run_task(card_id: int, project_path: str, prompt: str, phase: str,
             forced_provider: Optional[str], forced_model: str, card_title: str,
             project_name: str, member_id: Optional[int],
             auth_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """執行單一 AI 任務（使用 PTY 實現即時輸出串流）

    auth_info: 帳號認證資訊
        - auth_type: 'cli' | 'api_key'
        - oauth_token: CLI OAuth Token
        - api_key: API Key
    """
    auth_info = auth_info or {}

    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else PHASE_ROUTING.get(phase, "gemini")
    config = PROVIDERS.get(provider_name, PROVIDERS["gemini"])

    # 建構命令，支援成員指定的模型
    default_model = config.get("default_model", "")
    model = forced_model if forced_model else default_model
    cmd_parts = list(config["cmd_base"])
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd_parts.append(arg.replace("{prompt}", prompt))
        elif "{model}" in arg:
            cmd_parts.append(arg.replace("{model}", model))
        else:
            # 動態替換 --model 參數值
            cmd_parts.append(arg)

    # 如果成員有指定模型，替換 args 中的 --model 值
    if forced_model:
        for i, arg in enumerate(cmd_parts):
            if arg == "--model" and i + 1 < len(cmd_parts):
                cmd_parts[i + 1] = forced_model
                break

    stdin_prompt = config.get("stdin_prompt", False)

    # 完全隔離環境變數，避免干擾當前的 Claude Code session
    env = os.environ.copy()
    claude_env_keys = [k for k in env.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC", "GOOGLE", "GEMINI", "OPENAI"))]
    for key in claude_env_keys:
        env.pop(key, None)
    env["CLAUDE_CODE_ENTRY_POINT"] = "worker"

    # 根據帳號認證資訊設定環境變數
    auth_type = auth_info.get('auth_type', 'cli')
    if provider_name == "claude":
        if auth_type == 'api_key' and auth_info.get('api_key'):
            env["ANTHROPIC_API_KEY"] = auth_info['api_key']
            logger.info(f"[Task {card_id}] Using Anthropic API Key")
        elif auth_info.get('oauth_token'):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_info['oauth_token']
            logger.info(f"[Task {card_id}] Using Claude OAuth Token")
    elif provider_name == "gemini":
        if auth_type == 'api_key' and auth_info.get('api_key'):
            env["GEMINI_API_KEY"] = auth_info['api_key']
            logger.info(f"[Task {card_id}] Using Gemini API Key")
        # Gemini CLI 模式使用本機認證檔案，無需設定環境變數
    elif provider_name == "openai":
        if auth_info.get('api_key'):
            env["OPENAI_API_KEY"] = auth_info['api_key']
            logger.info(f"[Task {card_id}] Using OpenAI API Key")

    logger.info(f"[Task {card_id}] Executing {provider_name} in {project_path} (PTY mode)")
    logger.info(f"[Task {card_id}] Command: {' '.join(cmd_parts[:3])}...")

    # 廣播任務開始
    broadcast_event("task_started", {
        "card_id": card_id,
        "card_title": card_title,
        "project": project_name,
        "provider": provider_name
    })

    start_time = time.time()

    # 嘗試使用 PTY，失敗則 fallback 到 subprocess
    if platform.system() == "Windows":
        try:
            return run_task_pty_windows(
                card_id, project_path, cmd_parts, stdin_prompt, prompt,
                env, provider_name, card_title, project_name, member_id,
                config, start_time
            )
        except Exception as e:
            logger.warning(f"[Task {card_id}] PTY failed, fallback to subprocess: {e}")

    # Fallback: 使用一般 subprocess
    return run_task_subprocess(
        card_id, project_path, cmd_parts, stdin_prompt, prompt,
        env, provider_name, card_title, project_name, member_id,
        config, start_time
    )


def parse_stream_json_line(line: str) -> Optional[str]:
    """解析 stream-json 行，提取簡化的輸出摘要

    輸出規則：
    - system/init: 跳過
    - assistant/text: 回傳文字
    - assistant/tool_use: 回傳工具摘要（如 "🔧 Read: /path..."）
    - user/tool_result: 跳過（太冗長）
    - result: 回傳結果
    """
    try:
        data = json.loads(line.strip())
        msg_type = data.get("type")

        # 跳過 system 訊息
        if msg_type == "system":
            return None

        # 跳過 user 訊息（通常是工具結果，太冗長）
        if msg_type == "user":
            return None

        # assistant 類型：處理 text 和 tool_use
        if msg_type == "assistant":
            # 檢查頂層 content
            content = data.get("content", [])
            # 也檢查 message.content（嵌套結構）
            if not content:
                msg = data.get("message", {})
                content = msg.get("content", [])

            if content and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")

                    # 文字輸出
                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            return text

                    # 工具呼叫：顯示簡短摘要
                    if block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        # 提取關鍵參數作為摘要
                        summary = _format_tool_summary(tool_name, tool_input)
                        return summary

        # result 類型：最終結果
        if msg_type == "result":
            return data.get("result", "")

    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _format_tool_summary(tool_name: str, tool_input: dict) -> str:
    """格式化工具呼叫摘要"""
    # 常見工具的關鍵參數
    if tool_name == "Read":
        path = tool_input.get("file_path", "")
        return f"📖 Read: {_truncate_path(path)}"
    elif tool_name == "Write":
        path = tool_input.get("file_path", "")
        return f"✏️ Write: {_truncate_path(path)}"
    elif tool_name == "Edit":
        path = tool_input.get("file_path", "")
        return f"🔧 Edit: {_truncate_path(path)}"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")[:50]
        return f"💻 Bash: {cmd}{'...' if len(tool_input.get('command', '')) > 50 else ''}"
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"🔍 Glob: {pattern}"
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"🔍 Grep: {pattern}"
    elif tool_name == "TodoWrite":
        return "📋 更新待辦清單"
    elif tool_name == "Agent":
        desc = tool_input.get("description", "")
        return f"🤖 Agent: {desc}"
    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")[:40]
        return f"🌐 Fetch: {url}..."
    elif tool_name == "WebSearch":
        query = tool_input.get("query", "")
        return f"🔎 Search: {query}"
    else:
        return f"🔧 {tool_name}"


def _truncate_path(path: str, max_len: int = 50) -> str:
    """截斷過長的路徑"""
    if len(path) <= max_len:
        return path
    # 保留檔名和部分路徑
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 2:
        return path[:max_len] + "..."
    return f".../{'/'.join(parts[-2:])}"


def run_task_pty_windows(
    card_id: int, project_path: str, cmd_parts: list, stdin_prompt: bool,
    prompt: str, env: dict, provider_name: str, card_title: str,
    project_name: str, member_id: Optional[int], config: dict, start_time: float
) -> Dict[str, Any]:
    """Windows PTY 執行（使用 pywinpty 實現即時輸出）"""
    from winpty import PtyProcess
    import re
    import threading

    # 保存原始工作目錄
    original_cwd = os.getcwd()

    # 找出需要刪除的 CLAUDE 相關環境變數
    claude_env_keys = [k for k in os.environ.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
    old_claude_env = {k: os.environ.get(k) for k in claude_env_keys}

    # 從 os.environ 中刪除這些變數（這是 PTY 關鍵！）
    for key in claude_env_keys:
        del os.environ[key]

    # 設定我們需要的環境變數
    old_env = {k: os.environ.get(k) for k in env.keys()}
    os.environ.update(env)
    os.chdir(project_path)

    logger.info(f"[Task {card_id}] PTY env cleaned: removed {claude_env_keys}")

    # 檢查是否使用 stream-json 格式
    stream_json = config.get("stream_json", False)
    output_lines = []
    result_text_parts = []  # 收集實際的文字輸出

    # 心跳機制：每 5 秒發送進度更新
    heartbeat_stop = threading.Event()
    heartbeat_interval = 5  # 秒

    def heartbeat_worker():
        elapsed = 0
        while not heartbeat_stop.wait(heartbeat_interval):
            elapsed += heartbeat_interval
            broadcast_log(card_id, f"⏳ 處理中... ({elapsed}s)\n")

    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()

    try:
        # 使用 PtyProcess.spawn
        pty_process = PtyProcess.spawn(cmd_parts)

        # 如果需要 stdin，先寫入 prompt
        if stdin_prompt:
            pty_process.write(prompt + "\n")

        # 使用 read() 讀取並按行處理
        buffer = ""
        while pty_process.isalive():
            try:
                chunk = pty_process.read(512)
                if chunk:
                    output_lines.append(chunk)
                    buffer += chunk

                    # 按行處理
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)

                        if stream_json:
                            # 解析 stream-json，提取文字
                            # 先清理 ANSI codes
                            clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
                            if clean_line.strip().startswith("{"):
                                text = parse_stream_json_line(clean_line)
                                if text:
                                    result_text_parts.append(text)
                                    broadcast_log(card_id, text)
                        else:
                            broadcast_log(card_id, line + "\n")
            except EOFError:
                break
            except Exception as e:
                logger.warning(f"[Task {card_id}] PTY read error: {e}")
                time.sleep(0.05)

        # 讀取剩餘輸出
        try:
            while True:
                chunk = pty_process.read(512)
                if not chunk:
                    break
                output_lines.append(chunk)
                buffer += chunk
        except EOFError:
            pass

        # 處理剩餘 buffer
        if buffer:
            if stream_json:
                for line in buffer.split("\n"):
                    clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
                    if clean_line.strip().startswith("{"):
                        text = parse_stream_json_line(clean_line)
                        if text:
                            result_text_parts.append(text)
                            broadcast_log(card_id, text)
            else:
                broadcast_log(card_id, buffer)

        # 取得退出碼
        pty_process.wait()
        exit_code = pty_process.exitstatus or 0

    finally:
        # 停止心跳線程
        heartbeat_stop.set()

        # 恢復環境
        os.chdir(original_cwd)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # 恢復被刪除的 CLAUDE 環境變數
        for k, v in old_claude_env.items():
            if v is not None:
                os.environ[k] = v

    output = "".join(output_lines)
    duration_ms = int((time.time() - start_time) * 1000)
    status = "success" if exit_code == 0 else "error"

    # 解析 token 用量
    token_info = {}
    # 如果是 stream_json，使用收集的文字部分作為輸出
    if stream_json and result_text_parts:
        actual_output = "".join(result_text_parts)
    else:
        actual_output = output
    if provider_name == "claude" and config.get("json_output"):
        token_info = parse_claude_json(output)
        token_info["duration_ms"] = duration_ms
        if token_info.get("result_text"):
            actual_output = token_info["result_text"]

    save_task_log(card_id, card_title, project_name, provider_name, member_id, status, token_info)

    return {
        "status": status,
        "output": actual_output,
        "provider": provider_name,
        "exit_code": exit_code,
        "token_info": token_info,
    }


def run_task_subprocess(
    card_id: int, project_path: str, cmd_parts: list, stdin_prompt: bool,
    prompt: str, env: dict, provider_name: str, card_title: str,
    project_name: str, member_id: Optional[int], config: dict, start_time: float
) -> Dict[str, Any]:
    """一般 subprocess 執行（fallback）"""
    import threading

    # 心跳機制
    heartbeat_stop = threading.Event()
    heartbeat_interval = 5

    def heartbeat_worker():
        elapsed = 0
        while not heartbeat_stop.wait(heartbeat_interval):
            elapsed += heartbeat_interval
            broadcast_log(card_id, f"⏳ 處理中... ({elapsed}s)\n")

    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()

    try:
        creation_flags = 0
        if platform.system() == "Windows":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            cmd_parts,
            cwd=project_path,
            stdin=subprocess.PIPE if stdin_prompt else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=creation_flags,
        )

        if stdin_prompt and proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()

        output_lines = []
        for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            output_lines.append(line)
            broadcast_log(card_id, line)

        proc.wait()

        output = "".join(output_lines)
        duration_ms = int((time.time() - start_time) * 1000)

        status = "success" if proc.returncode == 0 else "error"

        token_info = {}
        actual_output = output
        if provider_name == "claude" and config.get("json_output"):
            token_info = parse_claude_json(output)
            token_info["duration_ms"] = duration_ms
            if token_info.get("result_text"):
                actual_output = token_info["result_text"]

        save_task_log(card_id, card_title, project_name, provider_name, member_id, status, token_info)

        return {
            "status": status,
            "output": actual_output,
            "provider": provider_name,
            "exit_code": proc.returncode,
            "token_info": token_info,
        }

    except Exception as e:
        logger.exception(f"[Task {card_id}] Subprocess execution failed: {e}")
        save_task_log(card_id, card_title, project_name, provider_name, member_id, "error", {})
        return {"status": "error", "output": str(e), "provider": provider_name}

    finally:
        heartbeat_stop.set()


# ==========================================
# 主處理迴圈
# ==========================================
def process_pending_cards():
    """處理一輪 pending 卡片"""
    max_ws = get_max_workstations()
    running = get_running_count()

    if running >= max_ws:
        return  # 工作台已滿

    # 系統負載檢查
    if is_system_overloaded(cpu_threshold=90.0, mem_threshold=90.0):
        logger.warning("[Worker] System overloaded, skipping this round")
        return

    pending = get_pending_cards()

    for idx in pending:
        # 再次檢查工作台
        if get_running_count() >= max_ws:
            break

        with Session(engine) as session:
            stage_list = session.get(StageList, idx.list_id)
            list_name = stage_list.name if stage_list else "Unknown"
            project = session.get(Project, idx.project_id)

            # 判斷此階段是否需要 AI 處理（通用化，不再硬編碼列表名稱）
            should_ai_process = (
                stage_list
                and stage_list.is_ai_stage
                and stage_list.stage_type in ["auto_process", "auto_review"]
            )
        if not should_ai_process:
            update_card_status(idx.card_id, "idle")
            continue

        # 解析成員
        member_id, forced_provider, forced_model, member_slug, auth_info = resolve_member(idx.list_id, list_name.upper())

        # 成員忙碌檢查
        if member_id and is_member_busy(member_id):
            logger.info(f"[Worker] Member {member_id} busy, skip card {idx.card_id}")
            continue

        # 標記為 running
        mark_card_running(idx.card_id, member_id)
        logger.info(f"[Worker] Processing card {idx.card_id}: {idx.title}")

        # 讀取卡片內容
        with Session(engine) as session:
            idx_fresh = session.get(CardIndex, idx.card_id)
            project_obj = session.get(Project, idx.project_id)
            project_path = project_obj.path if project_obj else "."
            project_name = project_obj.name if project_obj else "Unknown"

        try:
            card_data = read_card(Path(idx.file_path))
        except Exception as e:
            logger.error(f"[Worker] Failed to read card {idx.card_id}: {e}")
            cron_job_id = _parse_cron_job_id(idx.title)
            if cron_job_id is not None and list_name in ("Scheduled", "Inbound"):
                # 排程卡片讀取失敗：寫 CronLog + 刪除卡片
                with Session(engine) as session:
                    from app.models.core import CronJob as CJ
                    cj = session.get(CJ, cron_job_id)
                    cj_name = cj.name if cj else ""
                save_cron_log(cron_job_id, cj_name, idx.card_id, idx.title,
                              idx.project_id, project_name, "", None,
                              "error", "", str(e), "", {})
                delete_card_completely(idx.card_id)
            else:
                update_card_status(idx.card_id, "failed", f"\n\n---\n\n### Error\n無法讀取卡片: {e}")
            broadcast_event("task_failed", {"card_id": idx.card_id, "reason": str(e)})
            continue

        # Inbound 任務：自動檢傷分類（成員 + 專案路徑）
        if list_name == "Inbound" and card_data.content:
            import re as _re
            _pp_match = _re.search(r'<!-- project_path: (.+?) -->', card_data.content)
            if _pp_match:
                project_path = _pp_match.group(1)
                logger.info(f"[Worker] Inbound task using project path: {project_path}")

        # 準備工作區
        workspace_dir = None
        if member_slug:
            workspace_dir = str(prepare_workspace(
                card_id=idx.card_id,
                member_slug=member_slug,
                provider=forced_provider or "claude",
                project_path=project_path,
                card_content=card_data.content,
            ))

        effective_cwd = workspace_dir or project_path
        _dialogue_hint = "\n\n請在所有輸出的最末行，用你的角色語氣寫一句簡短的任務總結（20字以內），格式：<!-- dialogue: 你的總結 -->"
        effective_prompt = ("請閱讀你的設定檔並執行本次任務。" if workspace_dir else card_data.content) + _dialogue_hint

        # 執行任務
        result = run_task(
            card_id=idx.card_id,
            project_path=effective_cwd,
            prompt=effective_prompt,
            phase=list_name.upper(),
            forced_provider=forced_provider,
            forced_model=forced_model,
            card_title=idx.title,
            project_name=project_name,
            member_id=member_id,
            auth_info=auth_info,
        )

        # 判斷是否為排程卡片
        cron_job_id = _parse_cron_job_id(idx.title)
        is_cron_card = cron_job_id is not None and list_name in ("Scheduled", "Inbound")

        new_status = "completed" if result["status"] == "success" else "failed"
        token_info = result.get("token_info", {})

        if is_cron_card:
            # === 排程卡片：寫入 CronLog + 刪除卡片 ===
            output_text = result.get("output", "")
            error_msg = "" if new_status == "completed" else output_text

            # 取得 cron_job_name
            with Session(engine) as session:
                from app.models.core import CronJob
                cron_job = session.get(CronJob, cron_job_id)
                cron_job_name = cron_job.name if cron_job else ""

            save_cron_log(
                cron_job_id=cron_job_id,
                cron_job_name=cron_job_name,
                card_id=idx.card_id,
                card_title=idx.title,
                project_id=idx.project_id,
                project_name=project_name,
                provider=result.get("provider", ""),
                member_id=member_id,
                status="success" if new_status == "completed" else "error",
                output=output_text,
                error_message=error_msg,
                prompt_snapshot=card_data.content,
                token_info=token_info,
            )

            # 排程卡片：完成後刪除（不論成功失敗都刪，log 已記錄）
            delete_card_completely(idx.card_id)
        else:
            # === 一般卡片：輸出追加在 content 後面，用分隔線隔開 ===
            if result["status"] == "success":
                append_text = f"\n\n---\n\n### AI Output ({result['provider']})\n```\n{result['output'][:1000]}...\n```"
            else:
                append_text = f"\n\n---\n\n### Error ({result['provider']})\n{result['output']}"

            update_card_status(idx.card_id, new_status, append_text)

        # 廣播完成事件
        event = "task_completed" if new_status == "completed" else "task_failed"
        broadcast_event(event, {"card_id": idx.card_id, "status": new_status})

        # 生成 AVG 對話（從 AI 輸出解析）
        if member_id:
            dialogue_text = _extract_dialogue(result.get("output", ""))
            if dialogue_text:
                _save_member_dialogue(
                    member_id, idx.card_id, idx.title, project_name,
                    "task_complete" if new_status == "completed" else "task_failed",
                    dialogue_text,
                )

        # OneStack 任務完成回報
        try:
            from app.core.onestack_connector import connector as _os_connector
            if _os_connector.enabled:
                import asyncio
                asyncio.run(_os_connector.report_task_completion(
                    card_id=idx.card_id,
                    output=result.get("output", ""),
                    status=result.get("status", "error"),
                    duration_ms=token_info.get("duration_ms", 0),
                    cost_usd=token_info.get("total_cost_usd", 0),
                ))
        except Exception as e:
            logger.debug(f"[OneStack] Report completion failed: {e}")

        # 寫入成員記憶
        if member_slug:
            try:
                output_preview = result.get("output", "")[:500]
                write_member_short_term_memory(
                    member_slug,
                    f"## 任務: {idx.title}\n專案: {project_name}\n結果: {result['status']}\n\n{output_preview}"
                )
            except Exception as e:
                logger.warning(f"[Memory] Failed: {e}")

        # 清理工作區
        if workspace_dir:
            cleanup_workspace(idx.card_id)

        logger.info(f"[Worker] Card {idx.card_id} {'cron_log+deleted' if is_cron_card else new_status}")


def main():
    """Worker 主程式"""
    logger.info("=" * 50)
    logger.info("Aegis Worker Starting... (generic stage routing)")
    logger.info(f"API Base: {API_BASE}")
    logger.info(f"Poll Interval: {POLL_INTERVAL}s")
    logger.info("=" * 50)

    # 啟動時清除暫停狀態（避免 updater 設了 paused=true 但重啟後無法恢復）
    try:
        with Session(engine) as session:
            paused = session.get(SystemSetting, "worker_paused")
            if paused and paused.value == "true":
                paused.value = "false"
                session.add(paused)
                session.commit()
                logger.info("[Worker] Cleared stale worker_paused flag on startup")
    except Exception as e:
        logger.warning(f"[Worker] Failed to clear paused flag: {e}")

    while True:
        try:
            if is_worker_paused():
                pass  # 靜默跳過
            else:
                process_pending_cards()
        except Exception as e:
            logger.error(f"[Worker Error] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
