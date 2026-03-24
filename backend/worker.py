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
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.poller import _parse_and_create_cards


def _link_project_into_workspace(workspace_dir: str, project_path: str) -> None:
    """在 workspace 中建立連結指向專案目錄的原始碼。

    策略：workspace 保持為 CWD（CLAUDE.md、.claude/ 安全在這裡），
    專案的原始碼透過連結方式映射進來，AI 修改 → 改動直接落在開發目錄。

    平台相容性：
    - Linux/macOS：使用 symlink（無需額外權限）
    - Windows 目錄：優先 junction（不需管理員權限），失敗才用 symlink
    - Windows 檔案：使用 hardlink（不需管理員權限），失敗才用 symlink

    好處：
    - 設定檔不會污染專案目錄、不會蓋掉專案的 .claude/ 或 skills
    - 改動直接落在 git repo，commit 自然生效
    - 清理 workspace 時連結直接刪除，不影響專案
    """
    import platform
    ws = Path(workspace_dir)
    proj = Path(project_path)

    if not proj.exists():
        return

    is_windows = platform.system() == "Windows"

    # workspace 自己的檔案，不要被覆蓋
    skip = {
        "CLAUDE.md", ".gemini.md", ".claude", ".gemini",
        ".mcp.json", ".gitconfig",
    }

    linked = 0
    for item in proj.iterdir():
        if item.name in skip or item.name.startswith(".aegis"):
            continue
        link_path = ws / item.name
        if link_path.exists() or link_path.is_symlink():
            continue
        try:
            if is_windows and item.is_dir():
                # Windows: junction 不需管理員權限（僅限目錄）
                import subprocess
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(item)],
                    check=True, capture_output=True, timeout=5,
                )
            else:
                link_path.symlink_to(item)
            linked += 1
        except Exception as e:
            logger.warning(f"[Workspace] Failed to link {item.name}: {e}")

    # .git 連結（讓 git 指令在 workspace 中也能用）
    git_link = ws / ".git"
    git_src = proj / ".git"
    if git_src.exists() and not git_link.exists():
        try:
            if is_windows:
                import subprocess
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(git_link), str(git_src)],
                    check=True, capture_output=True, timeout=5,
                )
            else:
                git_link.symlink_to(git_src)
            linked += 1
        except Exception:
            pass

    logger.info(f"[Workspace] Linked {linked} items from {proj} into {ws}")
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

PROVIDERS = {
    "gemini": {
        "cmd_base": ["gemini"],
        "args": ["-p", "{prompt}", "-y", "--model", "gemini-3.1-pro-preview"],
        "json_output": False,
    },
    "claude": {
        "cmd_base": ["claude"],
        # 使用 stream-json + verbose 實現即時串流輸出
        "args": ["--dangerously-skip-permissions", "--model", "sonnet",
                 "--output-format", "stream-json", "--verbose"],
        "json_output": False,
        "stream_json": True,  # 標記需要解析 stream-json
        "stdin_prompt": True,  # 避免 prompt 中的 --- 被 CLI parser 誤解析
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
    """透過 HTTP 發送 log 給 FastAPI 廣播，同時寫入 BroadcastLog"""
    try:
        # 過濾掉 ANSI escape codes 和控制字符
        import re
        clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
        clean_line = ''.join(c for c in clean_line if c.isprintable() or c in '\n\r\t')

        if not clean_line.strip():
            return  # 跳過空行

        # 寫入 BroadcastLog（臨時表）
        try:
            with Session(engine) as session:
                from app.models.core import BroadcastLog
                session.add(BroadcastLog(card_id=card_id, line=clean_line))
                session.commit()
        except Exception:
            pass  # 不影響廣播

        logger.info(f"[Broadcast] card={card_id} len={len(clean_line)}")
        from app.core.http_client import InternalAPI
        InternalAPI.broadcast_log(card_id, clean_line)
    except Exception as e:
        logger.warning(f"[Broadcast] Failed: {e}")
        pass


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


def get_member_accounts(member_id: int) -> list:
    """取得成員所有健康帳號（按 priority 排序），用於 fallback
    回傳 [(provider, model, auth_info, account_name), ...]
    """
    with Session(engine) as session:
        stmt = select(MemberAccount).where(
            MemberAccount.member_id == member_id
        ).order_by(MemberAccount.priority)
        bindings = session.exec(stmt).all()

        results = []
        for binding in bindings:
            account = session.get(Account, binding.account_id)
            if account and account.is_healthy:
                auth_info = {
                    'auth_type': getattr(account, 'auth_type', 'cli'),
                    'oauth_token': getattr(account, 'oauth_token', '') or '',
                    'api_key': getattr(account, 'api_key', '') or '',
                }
                results.append((
                    account.provider,
                    binding.model or "",
                    auth_info,
                    account.name or f"account-{account.id}",
                ))
        return results


def get_primary_provider(member_id: int) -> tuple:
    """從成員的主帳號取得 provider、model 和認證資訊（向下相容）"""
    accounts = get_member_accounts(member_id)
    if accounts:
        provider, model, auth_info, _ = accounts[0]
        return provider, model, auth_info
    return None, "", {}


def resolve_member(stage_list_id: int, phase: str) -> tuple:
    """解析任務應該由哪個成員執行
    回傳 (member_id, accounts_list, member_slug)
    accounts_list = [(provider, model, auth_info, account_name), ...]
    """
    with Session(engine) as session:
        # 1. 列表級指派
        stage_list = session.get(StageList, stage_list_id)
        if stage_list and stage_list.member_id:
            member = session.get(Member, stage_list.member_id)
            if member:
                accounts = get_member_accounts(member.id)
                logger.info(f"[Router] List '{stage_list.name}' → {member.name} ({len(accounts)} accounts)")
                return member.id, accounts, member.slug

        # 2. 專案預設成員（Inbound/Scheduled 等系統列表 fallback）
        if stage_list:
            project = session.get(Project, stage_list.project_id)
            if project and project.default_member_id:
                member = session.get(Member, project.default_member_id)
                if member:
                    accounts = get_member_accounts(member.id)
                    logger.info(f"[Router] Project '{project.name}' default → {member.name} ({len(accounts)} accounts)")
                    return member.id, accounts, member.slug

        # 3. 無指派
        return None, [], None


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
from app.core.stream_parsers import parse_claude_json  # 統一解析器


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

    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else "claude"
    config = PROVIDERS.get(provider_name, PROVIDERS["gemini"])

    # 建構命令，支援成員指定的模型
    default_model = config.get("default_model", "")
    model = forced_model if forced_model is not None else default_model
    cmd_parts = list(config["cmd_base"])
    model_replaced = False
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd_parts.append(arg.replace("{prompt}", prompt))
        elif "{model}" in arg:
            cmd_parts.append(arg.replace("{model}", model))
            model_replaced = True
        else:
            cmd_parts.append(arg)

    # 如果成員有指定模型且 placeholder 未處理，替換 args 中的 --model 值
    if forced_model is not None and not model_replaced:
        for i, arg in enumerate(cmd_parts):
            if arg == "--model" and i + 1 < len(cmd_parts):
                cmd_parts[i + 1] = forced_model
                break

    stdin_prompt = config.get("stdin_prompt", False)

    # 環境變數白名單隔離（透過 sandbox 模組）
    from app.core.sandbox import build_sanitized_env
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
    env = build_sanitized_env(project_id=_project_id)
    env["CLAUDE_CODE_ENTRY_POINT"] = "worker"

    # 注入 GitHub git credential（如果 workspace 有 .gitconfig）
    ws_gitconfig = os.path.join(project_path, ".gitconfig")
    if os.path.exists(ws_gitconfig):
        env["GIT_CONFIG_GLOBAL"] = ws_gitconfig

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

    # OneStack stream 轉發由 FastAPI 端的 internal/broadcast-event 處理

    # 如果 workspace 有 .gitconfig（GitHub PAT），注入環境變數
    _ws_gitconfig = Path(project_path) / ".gitconfig"
    if _ws_gitconfig.exists():
        env["GIT_CONFIG_GLOBAL"] = str(_ws_gitconfig)

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
    old_env = {k: os.environ.get(k) for k in env.keys()}

    # 檢查是否使用 stream-json 格式
    stream_json = config.get("stream_json", False)
    output_lines = []
    result_text_parts = []  # 收集實際的文字輸出

    # 心跳機制：只有靜止超過 20 秒才發送
    heartbeat_stop = threading.Event()
    last_activity = time.time()
    _idle_threshold = 20  # 秒

    def heartbeat_worker():
        while not heartbeat_stop.wait(5):
            idle = time.time() - last_activity
            if idle >= _idle_threshold:
                broadcast_log(card_id, f"⏳ 處理中... ({int(idle)}s)\n")

    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()

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

        # 使用 read() 讀取並按行處理
        buffer = ""
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
                    broadcast_log(card_id, "\n🛑 任務已被中止\n")
                    break

                chunk = pty_process.read(512)
                if chunk:
                    last_activity = time.time()
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
    project_name: str, member_id: Optional[int], config: dict, start_time: float
) -> Dict[str, Any]:
    """一般 subprocess 執行（fallback）"""
    import threading

    # 心跳機制：只有靜止超過 20 秒才發送
    heartbeat_stop = threading.Event()
    last_activity = time.time()
    _idle_threshold = 20

    def heartbeat_worker():
        while not heartbeat_stop.wait(5):
            idle = time.time() - last_activity
            if idle >= _idle_threshold:
                broadcast_log(card_id, f"⏳ 處理中... ({int(idle)}s)\n")

    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()

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
        for raw_line in proc.stdout:
            last_activity = time.time()
            line = raw_line.decode("utf-8", errors="replace")
            output_lines.append(line)
            broadcast_log(card_id, line)
            # 檢查 abort 信號
            if is_abort_requested(card_id):
                logger.info(f"[Task {card_id}] Abort signal received, killing process")
                proc.kill()
                clear_abort_signal(card_id)
                broadcast_log(card_id, "\n🛑 任務已被中止\n")
                break

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

    finally:
        heartbeat_stop.set()


# ==========================================
# 主處理迴圈
# ==========================================
def _execute_card_task(idx, list_name, stage_list, member_id, accounts_list, member_slug):
    """在 thread 中執行單張卡片任務（含 fallback、結果處理、清理）"""
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

    if is_chat_mode:
        # Chat 模式：不建 workspace，直接在專案目錄執行
        workspace_dir = None
        effective_cwd = project_path
        # 移除 chat metadata，只保留用戶訊息
        clean_content = _re_chat.sub(r'<!-- chat_id: .+? -->', '', card_data.content or "").strip()
        effective_prompt = clean_content or "你好"
        logger.info(f"[Worker] Chat mode: card={idx.card_id} chat_id={chat_id}")
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

    # 執行任務（含 fallback 機制）
    if not accounts_list:
        accounts_list = [("claude", "", {}, "default")]

    result = None
    for attempt_idx, (acct_provider, acct_model, acct_auth, acct_name) in enumerate(accounts_list):
        if attempt_idx > 0:
            logger.info(f"[Worker] Card {idx.card_id}: fallback → '{acct_name}' (priority={attempt_idx})")
            broadcast_log(idx.card_id, f"\n⚠️ 主帳號失敗，切換至備用帳號: {acct_name}\n")

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
        )

        if result["status"] == "success":
            if attempt_idx > 0:
                logger.info(f"[Worker] Card {idx.card_id}: succeeded with fallback account '{acct_name}'")
            break

        logger.warning(f"[Worker] Card {idx.card_id}: account '{acct_name}' failed (exit={result.get('exit_code')})")

    # result 一定有值（accounts_list 至少有 default）

    # 判斷是否為排程卡片（標題含 [cron_N] 即為排程卡片，不限 list）
    cron_job_id = _parse_cron_job_id(idx.title)
    is_cron_card = cron_job_id is not None

    new_status = "completed" if result["status"] == "success" else "failed"
    token_info = result.get("token_info", {})

    # 自動重試：失敗且尚未重試過 → 重設為 pending，下一輪 poll 會再撿起
    if new_status == "failed" and "### Error" not in card_data.content:
        logger.info(f"[Worker] Card {idx.card_id}: first failure, scheduling retry")
        error_note = f"\n\n### Error (retry scheduled)\n{result.get('output', '')[:200]}"
        update_card_status(idx.card_id, "pending", error_note)
        broadcast_event("task_failed", {"card_id": idx.card_id, "status": "retrying"})
        if workspace_dir:
            cleanup_workspace(idx.card_id)
        return

    if is_chat_mode:
        # === Chat 卡片：寫入 aegis_stream + 刪除卡片 ===
        # 從 stream-json 提取最終 AI 回應文字
        raw_output = result.get("output", "")
        output_text = token_info.get("result_text", "")
        if not output_text:
            # subprocess 模式：從多行 stream-json 提取 result 文字
            try:
                for line in raw_output.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("{") and '"subtype":"result"' in line:
                        rd = json.loads(line)
                        output_text = rd.get("result", "")
                        break
                if not output_text:
                    # fallback: 提取所有 assistant text 內容
                    texts = []
                    for line in raw_output.strip().split("\n"):
                        line = line.strip()
                        if not line.startswith("{"):
                            continue
                        try:
                            d = json.loads(line)
                            msg = d.get("message", {})
                            for part in (msg.get("content", []) if isinstance(msg.get("content"), list) else []):
                                if isinstance(part, dict) and part.get("type") == "text":
                                    texts.append(part["text"])
                        except Exception:
                            pass
                    if texts:
                        output_text = "\n".join(texts)
            except Exception:
                pass
        if not output_text:
            output_text = raw_output[:3000]
        try:
            from app.core.onestack_connector import connector
            if connector.enabled and chat_id:
                import threading, asyncio as _aio
                evt_type = "result" if new_status == "completed" else "error"
                def _stream_chat():
                    try:
                        loop = _aio.new_event_loop()
                        loop.run_until_complete(
                            connector.stream_event(idx.card_id, evt_type, output_text[:3000], member_slug, chat_id=chat_id)
                        )
                        loop.close()
                    except Exception:
                        pass
                threading.Thread(target=_stream_chat, daemon=True).start()
        except Exception:
            pass

        # Chat 卡片完成後刪除（不保留）
        delete_card_completely(idx.card_id)
        logger.info(f"[Worker] Chat card {idx.card_id} {new_status}, deleted")
        broadcast_event("task_completed" if new_status == "completed" else "task_failed",
                        {"card_id": idx.card_id, "status": new_status})
        return

    if is_cron_card:
        # === 排程卡片：寫入 CronLog + 刪除卡片 ===
        output_text = result.get("output", "")
        error_msg = "" if new_status == "completed" else output_text

        with Session(engine) as session:
            from app.models.core import CronJob
            cron_job = session.get(CronJob, cron_job_id)
            cron_job_name = cron_job.name if cron_job else ""

        # 排程卡片：依據 stage action 處理（預設 delete，可在 UI 調整）
        applied_action = _apply_worker_stage_action(idx, new_status)

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
            stage_action=applied_action,
        )
    else:
        # === 一般卡片：輸出追加在 content 後面，用分隔線隔開 ===
        if result["status"] == "success":
            append_text = f"\n\n---\n\n### AI Output ({result['provider']})\n```\n{result['output'][:1000]}...\n```"
        else:
            append_text = f"\n\n---\n\n### Error ({result['provider']})\n{result['output']}"

        # 檢查卡片是否在執行期間被 AI 移走（如會議流轉）
        # 如果 list_id 改變或 status 已被設為 pending，不覆蓋
        with Session(engine) as session:
            current_card = session.get(CardIndex, idx.card_id)
            card_relocated = (
                current_card
                and (current_card.list_id != idx.list_id or current_card.status == "pending")
            )

        if card_relocated:
            logger.info(f"[Worker] Card {idx.card_id}: relocated during execution (list {idx.list_id}→{current_card.list_id}), skip status update")
        else:
            update_card_status(idx.card_id, new_status, append_text)

            # 一般卡片也執行 stage action（流水線流轉）
            _apply_worker_stage_action(idx, new_status)

            # 自動 git 管理（需列表開啟 auto_commit）
            if project_path:
                stage_auto_commit = False
                try:
                    with Session(engine) as _s:
                        _sl = _s.get(StageList, idx.list_id)
                        stage_auto_commit = _sl.auto_commit if _sl else False
                except Exception:
                    pass
                if stage_auto_commit:
                    if new_status == "completed":
                        _auto_commit_on_success(project_path, idx.card_id, idx.title, member_slug)
                    else:
                        _auto_shelve_on_failure(project_path, idx.card_id, idx.title, member_slug)

        # 解析 AI 輸出中的 json:create_cards 區塊（跨成員協作、審查卡片等）
        output_text = result.get("output", "")
        if "json:create_cards" in output_text:
            try:
                with Session(engine) as session:
                    created_ids = _parse_and_create_cards(
                        output_text,
                        idx.project_id,
                        project_path,
                        session,
                        member_slug=member_slug,
                        source_card_id=idx.card_id,
                    )
                    if created_ids:
                        logger.info(f"[Worker] Card {idx.card_id} auto-created {len(created_ids)} cards: {created_ids}")
            except Exception as e:
                logger.warning(f"[Worker] Failed to parse create_cards: {e}")

    # 廣播完成事件
    event = "task_completed" if new_status == "completed" else "task_failed"
    broadcast_event(event, {"card_id": idx.card_id, "status": new_status})

    # OneStack stream 轉發由 FastAPI 端的 internal/broadcast-event 處理

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

    # 清理工作區（symlink 會隨 workspace 一起刪除，不影響專案）
    if workspace_dir:
        cleanup_workspace(idx.card_id)

    logger.info(f"[Worker] Card {idx.card_id} {'cron_log+deleted' if is_cron_card else new_status}")


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

        # 解析成員
        member_id, accounts_list, member_slug = resolve_member(idx.list_id, list_name.upper())

        # 成員忙碌檢查
        if member_id and is_member_busy(member_id):
            logger.info(f"[Worker] Member {member_id} busy, skip card {idx.card_id}")
            continue

        # 標記為 running（在主線程做，防止下一輪重複撿取）
        mark_card_running(idx.card_id, member_id)
        logger.info(f"[Worker] Processing card {idx.card_id}: {idx.title} (threaded)")

        # 在獨立 thread 中執行任務
        t = threading.Thread(
            target=_execute_card_task,
            args=(idx, list_name, stage_list, member_id, accounts_list, member_slug),
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
