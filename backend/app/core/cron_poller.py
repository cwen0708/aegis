import asyncio
import os
import json
import logging
from datetime import datetime, timezone
from sqlmodel import Session, select
from app.database import engine
from app.models.core import Card, StageList, Project, Tag, CardTagLink, CronJob, CardIndex, SystemSetting, TaskLog
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import sync_card_to_index, next_card_id
from app.core.telemetry import get_system_metrics
from croniter import croniter

logger = logging.getLogger(__name__)

# 模組級狀態（供 API 讀取）
last_check_at: str | None = None
paused_projects: set[int] = set()  # 被暫停排程的專案 ID


def _get_template_variables(session: Session) -> dict:
    """取得 prompt_template 變數替換用的系統狀態"""
    # 系統指標
    metrics = get_system_metrics()

    # Worker 狀態
    max_ws_setting = session.get(SystemSetting, "max_workstations")
    max_workstations = int(max_ws_setting.value) if max_ws_setting else 3

    running_cards = session.exec(
        select(CardIndex).where(CardIndex.status == "running")
    ).all()
    running_count = len(running_cards)

    pending_cards = session.exec(
        select(CardIndex).where(CardIndex.status == "pending")
    ).all()
    pending_summary = f"{len(pending_cards)} 張" if pending_cards else "無"

    # 最近失敗的任務（過去 1 小時）
    one_hour_ago = datetime.now(timezone.utc).isoformat()
    recent_logs = session.exec(
        select(TaskLog)
        .where(TaskLog.status == "error")
        .order_by(TaskLog.created_at.desc())
        .limit(5)
    ).all()
    if recent_logs:
        failures = [f"{log.card_title}" for log in recent_logs]
        recent_failures = ", ".join(failures[:3])
        if len(failures) > 3:
            recent_failures += f" 等 {len(failures)} 個"
    else:
        recent_failures = "無"

    return {
        "cpu_percent": f"{metrics['cpu_percent']:.1f}",
        "mem_percent": f"{metrics['memory_percent']:.1f}",
        "running_count": str(running_count),
        "max_workstations": str(max_workstations),
        "pending_cards_summary": pending_summary,
        "recent_failures": recent_failures,
    }


def _render_template(template: str, variables: dict) -> str:
    """替換 template 中的 {var} 佔位符"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _calculate_next_time(cron_expression: str) -> datetime:
    """計算下一次執行時間"""
    if not cron_expression:
        return None
    try:
        cron = croniter(cron_expression, datetime.now(timezone.utc))
        return cron.get_next(datetime)
    except Exception as e:
        logger.error(f"Invalid cron expression: {cron_expression}, error: {e}")
        return None

async def poll_local_cron_jobs():
    """輪詢本地的 CronJob 表，將到期的排程轉化為待執行的 Card"""
    global last_check_at
    now = datetime.now(timezone.utc)
    last_check_at = now.isoformat()
    now_str = now.isoformat()  # SQLite 需要 ISO 字串比較

    with Session(engine) as session:
        # 找出啟用且到期的任務 (next_scheduled_at <= now)
        due_jobs = session.exec(
            select(CronJob)
            .where(CronJob.is_enabled == True)
            .where(CronJob.next_scheduled_at <= now_str)
        ).all()

        if not due_jobs:
            print(f"[Cron Poller] {now.strftime('%H:%M:%S')} - No due jobs")
            return

        # 過濾掉被暫停排程的專案
        if paused_projects:
            due_jobs = [j for j in due_jobs if j.project_id not in paused_projects]
            if not due_jobs:
                return

        logger.info(f"[Cron Poller] Found {len(due_jobs)} due jobs in local DB. Creating Aegis Cards...")

        # 確保有 Ops 標籤
        ops_tag = session.exec(select(Tag).where(Tag.name == "Ops")).first()
        if not ops_tag:
            ops_tag = Tag(name="Ops", color="purple")
            session.add(ops_tag)
            session.commit()
            session.refresh(ops_tag)

        for job in due_jobs:
            # 找到專案的 Scheduled 列表（排程專用）
            sched_list = session.exec(
                select(StageList)
                .where(StageList.project_id == job.project_id)
                .where(StageList.name == "Scheduled")
            ).first()

            if not sched_list:
                logger.error(f"Cannot find Scheduled list for project {job.project_id}")
                continue

            # 組合 prompt 內容（替換變數）
            metadata = json.loads(job.metadata_json) if job.metadata_json else {}
            template_vars = _get_template_variables(session)

            rendered_prompt = _render_template(job.prompt_template, template_vars)
            content = f"【任務內容】\n{rendered_prompt}"
            if job.system_instruction:
                rendered_instruction = _render_template(job.system_instruction, template_vars)
                content = f"【系統指令】\n{rendered_instruction}\n\n{content}"

            full_content = f"## 營運排程元數據\n```json\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n```\n\n{content}"

            # 取得專案路徑（MD 檔案需要）
            project = session.get(Project, job.project_id)
            if not project or not project.path:
                logger.error(f"Cannot find project path for project {job.project_id}")
                continue

            # --- MD card file (primary) ---
            card_id = next_card_id(session)
            card_data = CardData(
                id=card_id,
                list_id=sched_list.id,
                title=f"[排程] {job.name}",
                description=job.description or 'Auto-generated from Aegis Cron',
                content=full_content,
                status="pending",
                tags=["Ops"],
            )
            fpath = card_file_path(project.path, card_id)
            write_card(fpath, card_data)
            sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

            # --- Dual-write: also create old Card ORM record ---
            old_card = Card(
                list_id=sched_list.id,
                title=card_data.title,
                description=card_data.description,
                content=full_content,
                status="pending",
            )
            session.add(old_card)
            session.commit()
            session.refresh(old_card)
            session.add(CardTagLink(card_id=old_card.id, tag_id=ops_tag.id))

            # 更新下次執行時間
            next_time = _calculate_next_time(job.cron_expression)
            if next_time:
                job.next_scheduled_at = next_time
            else:
                job.is_enabled = False # 如果算不出下次時間，先停用防呆
            session.add(job)
            
            session.commit()
            logger.info(f" -> Created MD Card {card_id} (ORM Card {old_card.id}) for CronJob '{job.name}', next run at: {next_time}")

async def start_cron_poller():
    """獨立的排程迴圈，每 60 秒檢查一次本地資料庫"""
    print("[Cron Poller] Starting Aegis Local Cron Poller...")
    logger.info("Starting Aegis Local Cron Poller...")
    while True:
        try:
            await poll_local_cron_jobs()
        except Exception as e:
            logger.error(f"[Cron Poller Error] {e}")
        await asyncio.sleep(60)
