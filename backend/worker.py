"""
Aegis Worker — 卡片任務的主要執行引擎（獨立程序）

⚠️ 此程序是卡片任務的唯一執行路徑。
   runner.py 只負責 chat/email 等即時互動，不處理卡片。

作為獨立於 FastAPI 的程序運行（aegis-worker.service），負責：
1. 每 3 秒掃描 CardIndex 中 status='pending' 的卡片
2. 三層路由（列表指派 → 專案預設 → 無指派）解析成員與帳號
3. 帳號 Fallback — 主帳號失敗自動切備用帳號
4. PTY 即時串流 — 每行 stdout 透過 HTTP 傳給 FastAPI 廣播到 WebSocket
5. stream-json 解析 — 解析 Claude 工具呼叫（📖 Read、💻 Bash 等）
6. 心跳機制 — 每 5 秒廣播進度，前端可見
7. CronLog — 排程卡片完成後寫入 CronLog + 依 stage action 處理
8. AVG 對話 — 解析 <!-- dialogue: xxx --> 並儲存 MemberDialogue
9. 環境隔離 — sandbox 白名單環境變數 + process group 隔離
"""
import os
import sys
import signal

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
from datetime import datetime, timezone, timedelta
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

# Abort 信號目錄
_INSTALL_ROOT = Path(__file__).resolve().parent
ABORT_DIR = _INSTALL_ROOT.parent / ".aegis" / "abort"
ABORT_DIR.mkdir(parents=True, exist_ok=True)


def is_abort_requested(card_id: int) -> bool:
    """檢查是否有 abort 請求（檔案信號）"""
    return (ABORT_DIR / str(card_id)).exists()


def clear_abort_signal(card_id: int):
    """清除 abort 信號"""
    f = ABORT_DIR / str(card_id)
    if f.exists():
        f.unlink(missing_ok=True)
from app.core.telemetry import is_system_overloaded
from app.core.model_router import resolve_model, get_failover_chain, get_failover_model
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.poller import _parse_and_create_cards


from app.core.task_workspace import link_project_into_workspace as _link_project_into_workspace
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
# Graceful Shutdown
# ==========================================
_shutdown_requested = False


def _handle_shutdown(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    logger.info(f"[Worker] Received signal {signum}, will shutdown after current task completes...")


# ==========================================
# 配置
# ==========================================
POLL_INTERVAL = 3  # 秒
API_BASE = "http://127.0.0.1:8899/api/v1"
MAX_WORKSTATIONS = 3  # 預設，啟動時從 DB 讀取

# Provider 設定統一由 executor 管理
from app.core.executor import PROVIDERS, build_command
from app.core.executor.providers import get_provider_config
from app.core.executor.emitter import clean_ansi as _clean_ansi


# ==========================================
# HTTP 工具
# ==========================================

def cleanup_broadcast_logs():
    """清理超過 24 小時的廣播記錄"""
    try:
        from app.models.core import BroadcastLog
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        with Session(engine) as session:
            old_logs = session.exec(
                select(BroadcastLog).where(BroadcastLog.created_at < cutoff)
            ).all()
            if old_logs:
                for log in old_logs:
                    session.delete(log)
                session.commit()
                logger.info(f"[Cleanup] Deleted {len(old_logs)} broadcast logs older than 24h")
    except Exception as e:
        logger.warning(f"[Cleanup] Failed: {e}")


def cleanup_media_files():
    """清理超過 24 小時的媒體暫存檔案（/tmp/aegis-media/）"""
    import glob
    media_dir = "/tmp/aegis-media"
    if not os.path.exists(media_dir):
        return
    try:
        cutoff = time.time() - 86400  # 24 小時
        count = 0
        for f in glob.glob(os.path.join(media_dir, "*")):
            if os.path.isfile(f) and os.path.getmtime(f) < cutoff:
                os.unlink(f)
                count += 1
        if count:
            logger.info(f"[Cleanup] Deleted {count} media files older than 24h")
    except Exception as e:
        logger.warning(f"[Cleanup] Media cleanup failed: {e}")


def broadcast_event(event_type: str, payload: dict):
    """透過 HTTP 發送事件給 FastAPI 廣播"""
    from app.core.http_client import InternalAPI
    InternalAPI.broadcast_event(event_type, payload)


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


# 成員解析統一由 executor.context 管理
from app.core.executor.context import resolve_member_for_task, MemberContext


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
from app.core.stream_parsers import parse_claude_json, parse_stream_json_text  # 統一解析器


def save_task_log(card_id: int, card_title: str, project_name: str, provider: str,
                  member_id: Optional[int], status: str, output: str, token_info: Dict[str, Any]):
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
                output=output,
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
                  error_message: str, prompt_snapshot: str, token_info: Dict[str, Any],
                  stage_action: str = ""):
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
                stage_action=stage_action,
            )
            session.add(log)
            session.commit()
            logger.info(f"[CronLog] Saved log for cron_job {cron_job_id}, status={status}, stage_action={stage_action}")
    except Exception as e:
        logger.warning(f"[CronLog] Failed to save: {e}")


def _git_has_changes(project_path: str) -> bool:
    """檢查 project_path 是否為 git repo 且有未提交的變更"""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_path, capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return False
        s = _sp.run(
            ["git", "status", "--porcelain"],
            cwd=project_path, capture_output=True, text=True, timeout=10
        )
        return bool(s.stdout.strip())
    except Exception:
        return False


def _git_commit_changes(project_path: str, card_id: int, card_title: str,
                        member_slug: str = "", prefix: str = "feat"):
    """git add -A + commit，回傳 commit hash 或 None"""
    import subprocess as _sp
    _sp.run(["git", "add", "-A"], cwd=project_path, timeout=10)
    clean_title = card_title.replace("[重構] ", "refactor: ").strip()
    if not any(clean_title.startswith(p) for p in ("feat:", "fix:", "refactor:", "chore:", "test:", "docs:")):
        clean_title = f"{prefix}: {clean_title}"
    author = member_slug or "aegis"
    msg = f"{clean_title}\n\nCard #{card_id} by {author}"
    r = _sp.run(
        ["git", "commit", "-m", msg, "--author", f"{author} <{author}@aegis.local>"],
        cwd=project_path, capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        h = _sp.run(["git", "rev-parse", "--short", "HEAD"],
                     cwd=project_path, capture_output=True, text=True, timeout=5)
        return h.stdout.strip()
    return None


def _auto_commit_on_success(project_path: str, card_id: int, card_title: str, member_slug: str = ""):
    """任務成功後自動 commit 到 main（僅本地，不 push）"""
    try:
        if not _git_has_changes(project_path):
            logger.info(f"[AutoCommit] Card {card_id}: no changes to commit")
            return
        h = _git_commit_changes(project_path, card_id, card_title, member_slug)
        logger.info(f"[AutoCommit] Card {card_id}: committed {h} to {project_path}")
    except Exception as e:
        logger.warning(f"[AutoCommit] Card {card_id}: failed: {e}")


def _auto_shelve_on_failure(project_path: str, card_id: int, card_title: str, member_slug: str = ""):
    """任務失敗後：將殘留變更保存到分支 failed/card-{id}，然後還原 main"""
    try:
        if not _git_has_changes(project_path):
            return
        import subprocess as _sp
        branch = f"failed/card-{card_id}"
        # 建分支、commit 失敗的變更
        _sp.run(["git", "checkout", "-b", branch], cwd=project_path, timeout=10)
        h = _git_commit_changes(project_path, card_id, card_title, member_slug, prefix="wip")
        # 切回 main
        _sp.run(["git", "checkout", "main"], cwd=project_path, timeout=10)
        logger.info(f"[AutoShelve] Card {card_id}: shelved {h} to branch {branch}, main is clean")
    except Exception as e:
        # 確保回到 main
        try:
            import subprocess as _sp2
            _sp2.run(["git", "checkout", "main"], cwd=project_path, timeout=10)
            _sp2.run(["git", "checkout", "--", "."], cwd=project_path, timeout=10)
            _sp2.run(["git", "clean", "-fd"], cwd=project_path, timeout=10)
        except Exception:
            pass
        logger.warning(f"[AutoShelve] Card {card_id}: failed: {e}")


def _apply_worker_stage_action(idx, new_status: str) -> str:
    """根據 StageList 的 on_success_action / on_fail_action 處理卡片。
    排程卡片不寫入 content（log 已記錄），只做 move/archive/delete。
    回傳實際執行的 action 字串（如 "move_to:42"、"delete"、"archive"、"none"）。
    """
    try:
        with Session(engine) as session:
            stage_list = session.get(StageList, idx.list_id)
            if not stage_list:
                # fallback: 找不到列表就刪除（舊行為）
                delete_card_completely(idx.card_id)
                return "delete"

            action = stage_list.on_success_action if new_status == "completed" else stage_list.on_fail_action

            if action == "delete":
                delete_card_completely(idx.card_id)
            elif action == "archive":
                update_card_status(idx.card_id, new_status)
                # 封存
                ci = session.get(CardIndex, idx.card_id)
                if ci:
                    file_path = Path(ci.file_path)
                    try:
                        card_data = read_card(file_path)
                        card_data.is_archived = True
                        write_card(file_path, card_data)
                        sync_card_to_index(session, card_data, ci.project_id, str(file_path))
                    except Exception:
                        pass
                orm_card = session.get(Card, idx.card_id)
                if orm_card:
                    orm_card.is_archived = True
                    session.add(orm_card)
                session.commit()
            elif action.startswith("move_to:"):
                target_list_id = int(action.split(":")[1])
                target_list = session.get(StageList, target_list_id)
                # 如果目標列表是 AI 處理階段，status 改為 pending（讓下一個成員撿起來）
                final_status = "pending" if target_list and target_list.is_ai_stage else new_status
                update_card_status(idx.card_id, final_status)
                # 移動
                ci = session.get(CardIndex, idx.card_id)
                if ci:
                    file_path = Path(ci.file_path)
                    try:
                        card_data = read_card(file_path)
                        card_data.list_id = target_list_id
                        card_data.status = final_status
                        write_card(file_path, card_data)
                        sync_card_to_index(session, card_data, ci.project_id, str(file_path))
                    except Exception:
                        pass
                orm_card = session.get(Card, idx.card_id)
                if orm_card:
                    orm_card.list_id = target_list_id
                    orm_card.status = final_status
                    session.add(orm_card)
                session.commit()
                logger.info(f"[Worker] Card {idx.card_id} moved to list {target_list_id} (status={final_status})")
            else:
                # none: 只更新狀態，不刪不移
                update_card_status(idx.card_id, new_status)
            return action
    except Exception as e:
        logger.warning(f"[Worker] _apply_worker_stage_action failed for card {idx.card_id}: {e}")
        # fallback: 舊行為刪除
        delete_card_completely(idx.card_id)
        return "delete"


def delete_card_completely(card_id: int):
    """完全刪除卡片（MD 檔 + CardIndex + Card ORM + BroadcastLog）"""
    try:
        from app.models.core import BroadcastLog
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

            # 清除廣播記錄（防止 card_id 重用時 log 混淆）
            old_logs = session.exec(
                select(BroadcastLog).where(BroadcastLog.card_id == card_id)
            ).all()
            for bl in old_logs:
                session.delete(bl)

            session.commit()
        logger.info(f"[Worker] Card {card_id} deleted completely")
    except Exception as e:
        logger.warning(f"[Worker] Failed to delete card {card_id}: {e}")


def _parse_cron_job_id(title: str) -> Optional[int]:
    """從卡片標題解析 cron_job_id，如 '[cron_43] xxx' -> 43"""
    import re
    m = re.match(r'\[cron_(\d+)\]', title)
    return int(m.group(1)) if m else None



# ==========================================
# 任務執行（PTY 模式，即時串流輸出）
# ==========================================
def run_task(card_id: int, project_path: str, prompt: str, phase: str,
             forced_provider: Optional[str], forced_model: str, card_title: str,
             project_name: str, member_id: Optional[int],
             auth_info: Optional[Dict[str, str]] = None,
             resume_session_id: Optional[str] = None,
             emitter=None) -> Dict[str, Any]:
    """執行單一 AI 任務（使用 PTY 實現即時輸出串流）

    auth_info: 帳號認證資訊
        - auth_type: 'cli' | 'api_key'
        - oauth_token: CLI OAuth Token
        - api_key: API Key
    emitter: StreamEmitter（可選，None 則用 broadcast_log fallback）
    """
    auth_info = auth_info or {}

    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else "claude"
    config = get_provider_config(provider_name)

    # 透過 executor 建構命令（統一 provider 設定）
    from app.core.executor.auth import get_mcp_config_path as _get_mcp
    mcp_path = _get_mcp(member_id) if member_id and provider_name == "claude" else None
    cmd_parts, stdin_prompt = build_command(
        provider=provider_name,
        prompt=prompt,
        model=forced_model or "",
        mode="task",
        mcp_config_path=mcp_path,
        resume_session_id=resume_session_id,
    )
    # 加上 -- 終止符，防止 prompt 中 --- 被 CLI parser 誤解析
    if provider_name == "claude" and "--" not in cmd_parts:
        cmd_parts.append("--")

    # 環境變數組裝（透過統一的 EnvironmentBuilder API）
    from app.core.env_builder import EnvironmentBuilder

    # 從 project_path 反查 project_id 用於注入專案環境變數
    _project_id = None
    try:
        with Session(engine) as _s:
            _proj = _s.exec(select(Project).where(Project.path == project_path)).first()
            if not _proj:
                # workspace 情況下，嘗試從 card 的 project_id 查
                _idx = _s.get(CardIndex, card_id)
                if _idx:
                    _project_id = _idx.project_id
            else:
                _project_id = _proj.id
    except Exception:
        pass

    # Git config 路徑（如果 workspace 有 .gitconfig）
    ws_gitconfig = os.path.join(project_path, ".gitconfig")

    env = (EnvironmentBuilder()
        .with_system_keys()
        .with_project_vars(_project_id)
        .with_global_api_keys()
        .with_entry_point("worker")
        .with_git_config(ws_gitconfig)
        .with_auth(provider_name, auth_info, log_prefix=f"[Task {card_id}]")
        .build())

    logger.info(f"[Task {card_id}] Executing {provider_name} in {project_path} (PTY mode)")
    logger.info(f"[Task {card_id}] Command: {' '.join(cmd_parts[:3])}...")

    # 廣播任務開始
    broadcast_event("task_started", {
        "card_id": card_id,
        "card_title": card_title,
        "project": project_name,
        "provider": provider_name
    })

    # OneStack stream 轉發由 FastAPI 端的 internal/broadcast-event 處理

    start_time = time.time()

    # LLM 審計日誌 — 包裝整個 LLM 呼叫
    from app.core.llm_audit import LLMAuditContext
    audit = LLMAuditContext(
        provider=provider_name,
        card_id=card_id,
        member_id=member_id,
    )

    with audit:
        # 嘗試使用 PTY，失敗則 fallback 到 subprocess
        result = None
        if platform.system() == "Windows":
            try:
                result = run_task_pty_windows(
                    card_id, project_path, cmd_parts, stdin_prompt, prompt,
                    env, provider_name, card_title, project_name, member_id,
                    config, start_time, emitter=emitter
                )
            except Exception as e:
                logger.warning(f"[Task {card_id}] PTY failed, fallback to subprocess: {e}")

        if result is None:
            # Fallback: 使用一般 subprocess
            result = run_task_subprocess(
                card_id, project_path, cmd_parts, stdin_prompt, prompt,
                env, provider_name, card_title, project_name, member_id,
                config, start_time, emitter=emitter
            )

        # 從結果填入 token 用量
        audit.record.status = result.get("status", "error")
        audit.fill_from_token_info(result.get("token_info", {}))

    return result



def run_task_pty_windows(
    card_id: int, project_path: str, cmd_parts: list, stdin_prompt: bool,
    prompt: str, env: dict, provider_name: str, card_title: str,
    project_name: str, member_id: Optional[int], config: dict, start_time: float,
    emitter=None
) -> Dict[str, Any]:
    """Windows PTY 執行（使用 pywinpty 實現即時輸出）"""
    from winpty import PtyProcess
    import re
    from app.core.executor.heartbeat import heartbeat_monitor

    # 保存原始工作目錄
    original_cwd = os.getcwd()

    # 找出需要刪除的 CLAUDE 相關環境變數
    claude_env_keys = [k for k in os.environ.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
    old_claude_env = {k: os.environ.get(k) for k in claude_env_keys}
    old_env = {k: os.environ.get(k) for k in env.keys()}

    # 檢查是否使用 stream-json 格式
    stream_json = config.get("stream_json", False)
    output_lines = []
    result_text_parts = []  # 收集實際的文字輸出
    # emitter 由 _execute_card_task 永遠傳入（_HookEmitter）

    try:
        # 從 os.environ 中刪除 CLAUDE 相關變數（這是 PTY 關鍵！）
        for key in claude_env_keys:
            del os.environ[key]

        # 設定我們需要的環境變數
        os.environ.update(env)
        os.chdir(project_path)

        logger.info(f"[Task {card_id}] PTY env cleaned: removed {claude_env_keys}")
        # 使用 PtyProcess.spawn
        pty_process = PtyProcess.spawn(cmd_parts)

        # 如果需要 stdin，先寫入 prompt
        if stdin_prompt:
            pty_process.write(prompt + "\n")

        # 使用 read() 讀取並按行處理（heartbeat_monitor 管理心跳）
        buffer = ""
        with heartbeat_monitor(emitter) as touch:
            while pty_process.isalive():
                try:
                    # 檢查 abort 信號
                    if is_abort_requested(card_id):
                        logger.info(f"[Task {card_id}] Abort signal received, killing PTY process")
                        try:
                            import signal as _sig
                            os.kill(pty_process.pid, _sig.SIGKILL)
                        except Exception:
                            pass
                        clear_abort_signal(card_id)
                        emitter.emit_output("\n🛑 任務已被中止\n")
                        break

                    chunk = pty_process.read(512)
                    if chunk:
                        touch()
                        output_lines.append(chunk)
                        buffer += chunk

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if stream_json:
                                clean_line = _clean_ansi(line)
                                if clean_line.strip().startswith("{"):
                                    emitter.emit_raw(clean_line)
                                    text = parse_stream_json_text(clean_line)
                                    if text:
                                        result_text_parts.append(text)
                            else:
                                emitter.emit_output(line + "\n")
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
                    clean_line = _clean_ansi(line)
                    if clean_line.strip().startswith("{"):
                        emitter.emit_raw(clean_line)
                        text = parse_stream_json_text(clean_line)
                        if text:
                            result_text_parts.append(text)
            else:
                emitter.emit_output(buffer)

        # 取得退出碼
        pty_process.wait()
        exit_code = pty_process.exitstatus or 0

    finally:
        # heartbeat_monitor 在 with 結束時自動停止

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
    elif provider_name == "openai" and config.get("stream_json"):
        # OpenAI stream_json 模式：與 Claude 相同的 stream-json 解析路徑
        if result_text_parts:
            actual_output = "".join(result_text_parts)
        token_info = emitter.token_info if emitter else {}
        token_info["duration_ms"] = duration_ms
    elif provider_name == "openai" and config.get("json_output"):
        from app.core.stream_parsers import parse_openai_json
        token_info = parse_openai_json(output)
        token_info["duration_ms"] = duration_ms
        if token_info.get("result_text"):
            actual_output = token_info["result_text"]

    save_task_log(card_id, card_title, project_name, provider_name, member_id, status, actual_output, token_info)

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
    project_name: str, member_id: Optional[int], config: dict, start_time: float,
    emitter=None
) -> Dict[str, Any]:
    """一般 subprocess 執行（fallback）"""
    from app.core.executor.heartbeat import heartbeat_monitor

    # subprocess 心跳用 StreamEmitter fallback
    # emitter 由 _execute_card_task 永遠傳入

    try:
        from app.core.sandbox import get_popen_kwargs
        popen_kwargs = get_popen_kwargs()

        proc = subprocess.Popen(
            cmd_parts,
            cwd=project_path,
            stdin=subprocess.PIPE if stdin_prompt else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **popen_kwargs,
        )

        if stdin_prompt and proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()

        output_lines = []
        result_text_parts = []
        stream_json = config.get("stream_json", False)
        with heartbeat_monitor(emitter) as touch:
            for raw_line in proc.stdout:
                touch()
                line = raw_line.decode("utf-8", errors="replace")
                output_lines.append(line)
                if stream_json:
                    clean = line.strip()
                    if clean.startswith("{") and emitter:
                        emitter.emit_raw(clean)
                        text = parse_stream_json_text(clean)
                        if text:
                            result_text_parts.append(text)
                elif emitter:
                    emitter.emit_output(line)
                # 檢查 abort 信號
                if is_abort_requested(card_id):
                    logger.info(f"[Task {card_id}] Abort signal received, killing process")
                    proc.kill()
                    clear_abort_signal(card_id)
                    if emitter:
                        emitter.emit_output("\n🛑 任務已被中止\n")
                    break

        proc.wait()

        output = "".join(output_lines)
        duration_ms = int((time.time() - start_time) * 1000)

        status = "success" if proc.returncode == 0 else "error"

        token_info = {}
        actual_output = output
        if stream_json and result_text_parts:
            actual_output = "".join(result_text_parts)
            token_info = emitter.token_info if emitter else {}
            token_info["duration_ms"] = duration_ms
        elif provider_name == "claude" and config.get("json_output"):
            token_info = parse_claude_json(output)
            token_info["duration_ms"] = duration_ms
            if token_info.get("result_text"):
                actual_output = token_info["result_text"]
        elif provider_name == "openai" and config.get("json_output"):
            from app.core.stream_parsers import parse_openai_json
            token_info = parse_openai_json(output)
            token_info["duration_ms"] = duration_ms
            if token_info.get("result_text"):
                actual_output = token_info["result_text"]

        save_task_log(card_id, card_title, project_name, provider_name, member_id, status, actual_output, token_info)

        return {
            "status": status,
            "output": actual_output,
            "provider": provider_name,
            "exit_code": proc.returncode,
            "token_info": token_info,
        }

    except Exception as e:
        logger.exception(f"[Task {card_id}] Subprocess execution failed: {e}")
        save_task_log(card_id, card_title, project_name, provider_name, member_id, "error", str(e), {})
        return {"status": "error", "output": str(e), "provider": provider_name}


# ==========================================
# 主處理迴圈
# ==========================================
from app.core.task_result import (
    handle_chat_result as _handle_chat_result_impl,
    handle_cron_result as _handle_cron_result_impl,
    handle_regular_result as _handle_regular_result_impl,
    post_task_hooks as _post_task_hooks_impl,
)


def _handle_chat_result(idx, result, new_status, token_info, member_slug, chat_id):
    _handle_chat_result_impl(idx, result, new_status, token_info, member_slug, chat_id,
                             broadcast_event=broadcast_event, delete_card_completely=delete_card_completely)


def _handle_cron_result(idx, result, new_status, token_info, card_data, project_name, member_id, cron_job_id):
    _handle_cron_result_impl(idx, result, new_status, token_info, card_data, project_name, member_id, cron_job_id,
                             save_cron_log=save_cron_log, apply_stage_action=_apply_worker_stage_action)


def _handle_regular_result(idx, result, new_status, card_data, project_path, member_slug):
    _handle_regular_result_impl(idx, result, new_status, card_data, project_path, member_slug,
                                update_card_status=update_card_status, apply_stage_action=_apply_worker_stage_action,
                                auto_commit_on_success=_auto_commit_on_success, auto_shelve_on_failure=_auto_shelve_on_failure,
                                parse_and_create_cards=_parse_and_create_cards)


def _post_task_hooks(idx, result, new_status, token_info, card_data, project_name, member_id, member_slug, workspace_dir, cron_job_id):
    _post_task_hooks_impl(idx, result, new_status, token_info, card_data, project_name, member_id, member_slug, workspace_dir, cron_job_id)


def _execute_card_task(idx, list_name, stage_list, ctx: MemberContext):
    """在 thread 中執行單張卡片任務（含 fallback、結果處理、清理）"""
    # 從 MemberContext 解構（內部程式碼向後相容）
    member_id = ctx.member_id
    accounts_list = ctx.accounts_as_tuples()
    member_slug = ctx.member_slug or ""
    # 讀取卡片內容
    with Session(engine) as session:
        idx_fresh = session.get(CardIndex, idx.card_id)
        project_obj = session.get(Project, idx.project_id)
        project_path = project_obj.path if project_obj else "."
        project_name = project_obj.name if project_obj else "Unknown"

    try:
        card_data = read_card(Path(idx.file_path))
        # description fallback：content 為空時，把 description 當作任務提示詞
        if not card_data.content.strip() and card_data.description:
            card_data.content = card_data.description
    except Exception as e:
        logger.error(f"[Worker] Failed to read card {idx.card_id}: {e}")
        cron_job_id = _parse_cron_job_id(idx.title)
        if cron_job_id is not None:
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
        return

    # Inbound 任務：自動檢傷分類（成員 + 專案路徑）
    if list_name == "Inbound" and card_data.content:
        import re as _re
        _pp_match = _re.search(r'<!-- project_path: (.+?) -->', card_data.content)
        if _pp_match:
            project_path = _pp_match.group(1)
            logger.info(f"[Worker] Inbound task using project path: {project_path}")

    # 偵測 chat 模式（tags 含 Chat 或標題以 [chat] 開頭（向後相容））
    import re as _re_chat
    import json as _json_chat
    _card_tags = _json_chat.loads(idx.tags_json) if idx.tags_json else []
    _chat_match = _re_chat.search(r'<!-- chat_id: (.+?) -->', card_data.content or "")
    is_chat_mode = "Chat" in _card_tags or idx.title.startswith("[chat]") or _chat_match is not None
    chat_id = _chat_match.group(1) if _chat_match else None

    # Session Pool 查詢（chat 對話延續）
    _resume_session_id = None
    if is_chat_mode and chat_id:
        from app.core.session_pool import session_pool as _sp
        _resume_session_id, _ = _sp.get_or_create(chat_id)

    if is_chat_mode:
        # Chat 模式：不建 workspace，直接在專案目錄執行
        workspace_dir = None
        effective_cwd = project_path
        # 移除 chat metadata，只保留用戶訊息
        clean_content = _re_chat.sub(r'<!-- chat_id: .+? -->', '', card_data.content or "").strip()
        effective_prompt = clean_content or "你好"
        logger.info(f"[Worker] Chat mode: card={idx.card_id} chat_id={chat_id} resume={'yes' if _resume_session_id else 'new'}")
    else:
        # 準備工作區
        workspace_dir = None
        primary_provider = accounts_list[0][0] if accounts_list else "claude"
        if member_slug:
            workspace_dir = str(prepare_workspace(
                card_id=idx.card_id,
                member_slug=member_slug,
                provider=primary_provider,
                project_path=project_path,
                card_content=card_data.content,
                stage_name=stage_list.name if stage_list else "",
                stage_description=stage_list.description or "" if stage_list else "",
                stage_instruction=stage_list.system_instruction or "" if stage_list else "",
            ))

        # CWD 策略：workspace 為 CWD（CLAUDE.md + skills 在這裡）
        if workspace_dir:
            _link_project_into_workspace(workspace_dir, project_path)
        effective_cwd = workspace_dir or project_path
        _dialogue_hint = "\n\n請在所有輸出的最末行，用你的角色語氣寫一句簡短的任務總結（70字以內），格式：<!-- dialogue: 你的總結 -->"
        if workspace_dir:
            effective_prompt = (card_data.content.strip() or "請閱讀你的設定檔並執行本次任務。") + _dialogue_hint
        else:
            effective_prompt = card_data.content + _dialogue_hint

    # 建立 Hook 驅動的 StreamEmitter
    from app.hooks import collect_hooks
    from app.hooks.websocket import WebSocketHook
    from app.hooks.onestack import OneStackHook
    from app.hooks.event_log import EventLogHook
    from app.core.executor.emitter import HookEmitter

    task_hooks = collect_hooks("worker")
    for h in task_hooks:
        if isinstance(h, WebSocketHook):
            h.card_id = idx.card_id
        elif isinstance(h, OneStackHook):
            h.card_id = idx.card_id
            h.member_slug = member_slug
            h.chat_id = chat_id or ""
        elif isinstance(h, EventLogHook):
            h.card_id = idx.card_id
            h.project_path = project_path

    task_emitter = HookEmitter(task_hooks)

    # 執行任務（含 fallback 機制）
    if not accounts_list:
        accounts_list = [("claude", "", {}, "default")]

    # 卡片級模型覆蓋：若卡片 frontmatter 指定了 model，優先使用
    card_model = getattr(idx, "model", None) or None
    if card_model:
        accounts_list = [
            (provider, card_model, auth, name)
            for provider, _model, auth, name in accounts_list
        ]
        logger.info(f"[Worker] Card {idx.card_id}: card-level model override → {card_model}")
    else:
        # 成本感知模型路由：tag-based > complexity-based > 帳號預設
        try:
            card_tags = json.loads(getattr(idx, "tags_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            card_tags = []
        routed_model = resolve_model(card_tags, effective_prompt)
        if routed_model:
            accounts_list = [
                (provider, routed_model, auth, name)
                for provider, _model, auth, name in accounts_list
            ]
            logger.info(f"[Worker] Card {idx.card_id}: model route → {routed_model}")

    # Prompt Hardening：附加安全規則提醒，防止長對話稀釋安全限制
    from app.core.prompt_hardening import harden_prompt
    effective_prompt = harden_prompt(effective_prompt, project_path)

    # Data Classification Guard：送往 AI 前掃描敏感資料
    from app.core.data_classifier import guard_for_ai, SecurityBlock
    try:
        effective_prompt, _redact_map = guard_for_ai(effective_prompt)
    except SecurityBlock as e:
        logger.warning(f"[Worker] Card {idx.card_id}: Prompt blocked by security guard: {e}")
        update_card_status(idx.card_id, "failed", f"\n\n---\n\n### Error\n安全閘門阻擋：偵測到 S3 等級敏感資料，prompt 未送出。\n{e}")
        broadcast_event("task_failed", {"card_id": idx.card_id, "reason": f"SecurityBlock: {e}"})
        return

    result = None
    for attempt_idx, (acct_provider, acct_model, acct_auth, acct_name) in enumerate(accounts_list):
        if attempt_idx > 0:
            logger.info(f"[Worker] Card {idx.card_id}: fallback → '{acct_name}' (priority={attempt_idx})")
            task_emitter.emit_output(f"\n⚠️ 主帳號失敗，切換至備用帳號: {acct_name}\n")

        result = run_task(
            card_id=idx.card_id,
            project_path=effective_cwd,
            prompt=effective_prompt,
            phase=list_name.upper(),
            forced_provider=acct_provider,
            forced_model=acct_model,
            card_title=idx.title,
            project_name=project_name,
            member_id=member_id,
            auth_info=acct_auth,
            resume_session_id=_resume_session_id if is_chat_mode else None,
            emitter=task_emitter,
        )

        if result["status"] == "success":
            if attempt_idx > 0:
                logger.info(f"[Worker] Card {idx.card_id}: succeeded with fallback account '{acct_name}'")
            break

        logger.warning(f"[Worker] Card {idx.card_id}: account '{acct_name}' failed (exit={result.get('exit_code')})")

    # Provider Failover — 所有帳號都失敗時，嘗試備援 provider（最多 1 次）
    if result and result["status"] != "success":
        failover_chain = get_failover_chain(primary_provider)
        for fo_provider in failover_chain:
            fo_model = get_failover_model(fo_provider)
            if not fo_model:
                continue
            logger.info(f"[Worker] Card {idx.card_id}: provider failover → {fo_provider} ({fo_model})")
            task_emitter.emit_output(f"\n🔄 Provider failover: {primary_provider} → {fo_provider} ({fo_model})\n")

            result = run_task(
                card_id=idx.card_id,
                project_path=effective_cwd,
                prompt=effective_prompt,
                phase=list_name.upper(),
                forced_provider=fo_provider,
                forced_model=fo_model,
                card_title=idx.title,
                project_name=project_name,
                member_id=member_id,
                auth_info={},
                resume_session_id=_resume_session_id if is_chat_mode else None,
                emitter=task_emitter,
            )

            if result["status"] == "success":
                logger.info(f"[Worker] Card {idx.card_id}: succeeded with provider failover → {fo_provider}")
                break

            logger.warning(f"[Worker] Card {idx.card_id}: provider failover '{fo_provider}' failed (exit={result.get('exit_code')})")

    # result 一定有值（accounts_list 至少有 default）
    new_status = "completed" if result["status"] == "success" else "failed"
    token_info = result.get("token_info", {})

    # 自動重試
    if new_status == "failed" and "### Error" not in card_data.content:
        logger.info(f"[Worker] Card {idx.card_id}: first failure, scheduling retry")
        update_card_status(idx.card_id, "pending", f"\n\n### Error (retry scheduled)\n{result.get('output', '')[:200]}")
        broadcast_event("task_failed", {"card_id": idx.card_id, "status": "retrying"})
        if workspace_dir:
            cleanup_workspace(idx.card_id)
        return

    # 依卡片類型分派結果處理
    cron_job_id = _parse_cron_job_id(idx.title)
    if is_chat_mode:
        _handle_chat_result(idx, result, new_status, token_info, member_slug, chat_id)
        return
    elif cron_job_id is not None:
        _handle_cron_result(idx, result, new_status, token_info, card_data, project_name, member_id, cron_job_id)
    else:
        _handle_regular_result(idx, result, new_status, card_data, project_path, member_slug)

    # 共用後處理
    _post_task_hooks(idx, result, new_status, token_info, card_data, project_name, member_id, member_slug, workspace_dir, cron_job_id)


def auto_activate_idle_cards():
    """AI stage 裡的 idle 卡片自動改為 pending（讓 Worker 撿起來）"""
    with Session(engine) as session:
        idle_cards = session.exec(
            select(CardIndex).where(CardIndex.status == "idle")
        ).all()
        for idx in idle_cards:
            stage_list = session.get(StageList, idx.list_id)
            if stage_list and stage_list.is_ai_stage and stage_list.member_id:
                update_card_status(idx.card_id, "pending")
                logger.info(f"[Worker] Auto-activated idle card {idx.card_id} in AI stage '{stage_list.name}'")


def process_pending_cards():
    """處理一輪 pending 卡片（不同成員並行執行）"""
    import threading

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

            # 判斷此階段是否需要 AI 處理
            should_ai_process = (
                stage_list
                and stage_list.is_ai_stage
            )
        if not should_ai_process:
            update_card_status(idx.card_id, "idle")
            continue

        # 解析成員（統一由 executor.context 處理）
        ctx = resolve_member_for_task(idx.list_id)

        # 成員忙碌檢查
        if ctx.member_id and is_member_busy(ctx.member_id):
            logger.info(f"[Worker] Member {ctx.member_id} busy, skip card {idx.card_id}")
            continue

        # 標記為 running（在主線程做，防止下一輪重複撿取）
        mark_card_running(idx.card_id, ctx.member_id)
        logger.info(f"[Worker] Processing card {idx.card_id}: {idx.title} (threaded)")

        # 在獨立 thread 中執行任務
        t = threading.Thread(
            target=_execute_card_task,
            args=(idx, list_name, stage_list, ctx),
            name=f"card-{idx.card_id}",
            daemon=True,
        )
        t.start()


def main():
    """Worker 主程式"""
    logger.info("=" * 50)
    logger.info("Aegis Worker Starting... (generic stage routing)")
    logger.info(f"API Base: {API_BASE}")
    logger.info(f"Poll Interval: {POLL_INTERVAL}s")
    logger.info("=" * 50)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    logger.info("[Worker] Signal handlers registered (graceful shutdown enabled)")

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

    # 啟動時掃描 stale 的 running 卡片（上次重啟時中斷的任務）
    try:
        with Session(engine) as session:
            stale_cards = session.exec(
                select(CardIndex).where(CardIndex.status == "running")
            ).all()
            for stale in stale_cards:
                stage_list = session.get(StageList, stale.list_id)
                if not stage_list:
                    continue
                # 如果有 on_success_action（流水線），補做流轉
                action = stage_list.on_success_action
                if action and action.startswith("move_to:"):
                    target_id = int(action.split(":")[1])
                    target_list = session.get(StageList, target_id)
                    final_status = "pending" if target_list and target_list.is_ai_stage else "completed"
                    stale.status = final_status
                    stale.list_id = target_id
                    session.add(stale)
                    # 也更新 Card 表
                    orm_card = session.get(Card, stale.card_id)
                    if orm_card:
                        orm_card.status = final_status
                        orm_card.list_id = target_id
                        session.add(orm_card)
                    logger.info(f"[Worker] Recovered stale card {stale.card_id}: moved to list {target_id} (status={final_status})")
                else:
                    # 無流轉動作，標記為 completed
                    stale.status = "completed"
                    session.add(stale)
                    logger.info(f"[Worker] Recovered stale card {stale.card_id}: set to completed")
            if stale_cards:
                session.commit()
                logger.info(f"[Worker] Recovered {len(stale_cards)} stale cards on startup")
    except Exception as e:
        logger.warning(f"[Worker] Failed to recover stale cards: {e}")

    last_cleanup = time.time()
    last_chat_export = time.time()
    while not _shutdown_requested:
        try:
            if is_worker_paused():
                pass  # 靜默跳過
            else:
                auto_activate_idle_cards()
                process_pending_cards()

            # 每小時清理過期記錄和暫存檔案
            if time.time() - last_cleanup > 3600:
                cleanup_broadcast_logs()
                cleanup_media_files()
                last_cleanup = time.time()

            # 每 8 小時匯出對話記憶
            if time.time() - last_chat_export > 28800:
                try:
                    from app.core.chat_memory_export import export_recent_chats
                    export_recent_chats(hours=9)  # 多撈 1 小時避免邊界遺漏
                except Exception as e:
                    logger.warning(f"[ChatExport] Failed: {e}")
                last_chat_export = time.time()
        except Exception as e:
            logger.error(f"[Worker Error] {e}")

        # 從 DB 讀取輪詢間隔（允許動態調整）
        try:
            with Session(engine) as _s:
                _setting = _s.get(SystemSetting, "poll_interval")
                _interval = int(_setting.value) if _setting and _setting.value else POLL_INTERVAL
        except Exception:
            _interval = POLL_INTERVAL
        time.sleep(max(1, _interval))

    logger.info("[Worker] Graceful shutdown complete.")


if __name__ == "__main__":
    main()
