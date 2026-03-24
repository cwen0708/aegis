import asyncio
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlmodel import Session, select
from app.database import engine
from app.models.core import Card, StageList, Project, Tag, CardTagLink, CronJob, CardIndex, SystemSetting, TaskLog, EmailMessage
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

    # 未分類 Email（供 email 分類排程使用）
    unclassified_emails = session.exec(
        select(EmailMessage)
        .where(EmailMessage.is_processed == False)
        .order_by(EmailMessage.created_at.desc())
        .limit(20)
    ).all()

    if unclassified_emails:
        email_lines = []
        for em in unclassified_emails:
            email_lines.append(
                f"[ID:{em.id}] From: {em.from_name} <{em.from_address}> | "
                f"Subject: {em.subject} | Date: {em.date}\n"
                f"Body: {em.body_text[:800]}\n"
            )
        unclassified_emails_text = "\n---\n".join(email_lines)
        unclassified_count = str(len(unclassified_emails))
    else:
        unclassified_emails_text = "（無未分類郵件）"
        unclassified_count = "0"

    # OneStack 相關變數
    owner_id_setting = session.get(SystemSetting, "onestack_owner_id")
    onestack_owner_id = owner_id_setting.value if owner_id_setting else ""
    endpoint_setting = session.get(SystemSetting, "onestack_endpoint")
    onestack_endpoint = endpoint_setting.value if endpoint_setting else ""

    return {
        "cpu_percent": f"{metrics['cpu_percent']:.1f}",
        "mem_percent": f"{metrics['memory_percent']:.1f}",
        "running_count": str(running_count),
        "max_workstations": str(max_workstations),
        "pending_cards_summary": pending_summary,
        "recent_failures": recent_failures,
        "unclassified_emails": unclassified_emails_text,
        "unclassified_email_count": unclassified_count,
        "onestack_owner_id": onestack_owner_id,
        "onestack_endpoint": onestack_endpoint,
    }


def _render_template(template: str, variables: dict) -> str:
    """替換 template 中的 {var} 佔位符"""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _get_system_timezone(session: Session = None) -> str:
    """從系統設定取得時區，預設 Asia/Taipei"""
    if session:
        tz_setting = session.get(SystemSetting, "timezone")
        if tz_setting and tz_setting.value:
            return tz_setting.value
    return "Asia/Taipei"


def _calculate_next_time(cron_expression: str, tz_name: str = "UTC") -> datetime:
    """計算下一次執行時間。Cron 表達式統一以 UTC 解析，返回 UTC aware datetime。"""
    if not cron_expression:
        return None
    try:
        now_utc = datetime.now(timezone.utc)
        cron = croniter(cron_expression, now_utc)
        next_utc = cron.get_next(datetime)
        if next_utc.tzinfo is None:
            next_utc = next_utc.replace(tzinfo=timezone.utc)
        return next_utc
    except Exception as e:
        logger.error(f"Invalid cron expression: {cron_expression}, error: {e}")
        return None

def _parse_datetime(dt_str: str) -> datetime | None:
    """解析各種格式的日期字串為 datetime（統一處理格式不一致問題）"""
    if not dt_str:
        return None
    # 移除尾部 +00:00 或 Z
    dt_str = dt_str.replace("+00:00", "").replace("Z", "").strip()
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def create_card_for_cron_job(session: Session, job: CronJob, ops_tag: Tag = None, update_next_time: bool = True) -> tuple:
    """
    為 CronJob 建立執行卡片。
    回傳 (card_id, error_message)。card_id=None 表示跳過或失敗。
    """
    cron_tag = f"cron_{job.id}"
    tz_name = _get_system_timezone(session)

    # 去重：檢查是否已存在待處理/執行中的卡片（failed 不阻擋下次觸發）
    # 向後相容：同時檢查 tags_json（新）和 title（舊）
    from sqlalchemy import or_
    existing = session.exec(
        select(CardIndex)
        .where(or_(
            CardIndex.tags_json.contains(cron_tag),
            CardIndex.title.contains(cron_tag),
        ))
        .where(CardIndex.status.in_(["pending", "running"]))
    ).first()
    if existing:
        if update_next_time:
            next_time = _calculate_next_time(job.cron_expression, tz_name)
            if next_time:
                job.next_scheduled_at = next_time
                session.add(job)
                session.commit()
        return None, f"已有卡片 {existing.card_id}（狀態: {existing.status}）"

    # 確保 Ops tag
    if not ops_tag:
        ops_tag = session.exec(select(Tag).where(Tag.name == "Ops")).first()
        if not ops_tag:
            ops_tag = Tag(name="Ops", color="purple")
            session.add(ops_tag)
            session.commit()
            session.refresh(ops_tag)

    # 組合 prompt
    metadata = json.loads(job.metadata_json) if job.metadata_json else {}

    # 決定目標列表：target_list_id > metadata.target_list > "Scheduled"
    sched_list = None
    if job.target_list_id:
        sched_list = session.get(StageList, job.target_list_id)
    if not sched_list:
        target_list_name = metadata.get("target_list", "Scheduled")
        sched_list = session.exec(
            select(StageList)
            .where(StageList.project_id == job.project_id)
            .where(StageList.name == target_list_name)
        ).first()
    if not sched_list:
        return None, f"找不到目標列表（project {job.project_id}）"

    template_vars = _get_template_variables(session)
    rendered_prompt = _render_template(job.prompt_template, template_vars)
    content = f"【任務內容】\n{rendered_prompt}"
    if job.system_instruction:
        rendered_instruction = _render_template(job.system_instruction, template_vars)
        content = f"【系統指令】\n{rendered_instruction}\n\n{content}"

    full_content = f"## 營運排程元數據\n```json\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n```\n\n{content}"

    project = session.get(Project, job.project_id)
    if not project or not project.path:
        return None, f"找不到專案路徑（project {job.project_id}）"

    # --- MD card file (primary) ---
    card_id = next_card_id(session)
    card_data = CardData(
        id=card_id,
        list_id=sched_list.id,
        title=job.name,
        description=job.description or 'Auto-generated from Aegis Cron',
        content=full_content,
        status="pending",
        tags=["Ops", cron_tag],
    )
    fpath = card_file_path(project.path, card_id)
    write_card(fpath, card_data)
    sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

    # --- Dual-write: ORM Card ---
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
    if update_next_time:
        next_time = _calculate_next_time(job.cron_expression, tz_name)
        if next_time:
            job.next_scheduled_at = next_time
        else:
            job.is_enabled = False
        session.add(job)

    session.commit()
    return card_id, None


async def poll_local_cron_jobs():
    """輪詢本地的 CronJob 表，將到期的排程轉化為待執行的 Card"""
    global last_check_at
    now = datetime.now(timezone.utc)
    last_check_at = now.isoformat()

    with Session(engine) as session:
        # 清理 Card ORM 殘留：超過 2 小時仍為 pending 且 CardIndex 已不存在的幽靈卡片
        try:
            cutoff = (now - timedelta(hours=2)).isoformat()
            stale_cards = session.exec(
                select(Card).where(Card.status == "pending", Card.created_at < cutoff)
            ).all()
            cleaned = 0
            for card in stale_cards:
                idx = session.get(CardIndex, card.id)
                if not idx or idx.status not in ("pending", "running"):
                    card.status = "expired"
                    session.add(card)
                    cleaned += 1
            if cleaned:
                session.commit()
                logger.info(f"[Cron Poller] Cleaned {cleaned} stale Card ORM entries")
        except Exception as e:
            logger.warning(f"[Cron Poller] Card cleanup failed: {e}")
        # 先取所有啟用的任務，然後在 Python 層比較時間（避免 SQLite 字串比較 bug）
        enabled_jobs = session.exec(
            select(CronJob).where(CronJob.is_enabled == True)
        ).all()

        # 過濾出到期的任務
        due_jobs = []
        for job in enabled_jobs:
            if isinstance(job.next_scheduled_at, str):
                next_time = _parse_datetime(job.next_scheduled_at)
            elif isinstance(job.next_scheduled_at, datetime):
                # 確保是 aware datetime
                next_time = job.next_scheduled_at if job.next_scheduled_at.tzinfo else job.next_scheduled_at.replace(tzinfo=timezone.utc)
            else:
                next_time = None
            if next_time and next_time <= now:
                due_jobs.append(job)

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
            card_id, error = create_card_for_cron_job(session, job, ops_tag, update_next_time=True)
            if error:
                logger.info(f"[Cron Poller] Skip {job.name}: {error}")
            elif card_id:
                logger.info(f"[Cron Poller] Created card {card_id} for '{job.name}'")

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
