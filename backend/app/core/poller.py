import asyncio
import logging
from pathlib import Path
from sqlmodel import Session, select
from app.database import engine
from app.models.core import Card, CardIndex, StageList, Project, SystemSetting
from app.core.card_file import CardData, read_card, write_card, card_file_path
from app.core.card_index import sync_card_to_index, query_pending_cards
from app.core.runner import run_ai_task, busy_members
from app.core.telemetry import is_system_overloaded

logger = logging.getLogger(__name__)

# 全域暫停旗標，供 API 控制
is_paused = False

# Card-level locks for safe concurrent MD file writes
_card_locks: dict[int, asyncio.Lock] = {}

def get_card_lock(card_id: int) -> asyncio.Lock:
    return _card_locks.setdefault(card_id, asyncio.Lock())


def _update_card_status(session: Session, idx: CardIndex, new_status: str, project_path: str) -> CardData | None:
    """Read MD file, update status, write back, sync index, dual-write Card ORM.
    Returns the updated CardData (or None on error)."""
    file_path = Path(idx.file_path)
    try:
        card_data = read_card(file_path)
    except Exception as e:
        logger.error(f"[Poller] Failed to read MD file {file_path}: {e}")
        return None

    card_data.status = new_status
    write_card(file_path, card_data)
    sync_card_to_index(session, card_data, idx.project_id, str(file_path))

    # Dual-write: keep Card ORM in sync during transition
    orm_card = session.get(Card, idx.card_id)
    if orm_card:
        orm_card.status = new_status
        session.add(orm_card)

    session.commit()
    return card_data


async def _process_pending_cards():
    """定期掃描 CardIndex 中 status='pending' 的卡片並派發給 AI"""
    if is_paused:
        return

    with Session(engine) as session:
        # 使用 CardIndex 查詢 pending 卡片（快速索引查詢，非檔案掃描）
        pending_entries = query_pending_cards(session)

        for idx in pending_entries:
            # Look up StageList and Project from the index's list_id
            stage_list = session.get(StageList, idx.list_id)
            list_name = stage_list.name if stage_list else "Unknown"
            project = session.get(Project, idx.project_id)

            # 只有特定的列表才需要喚醒 AI
            if list_name in ["Planning", "Developing", "Verifying", "Scheduled"]:

                # 防護機制：如果系統負載過高，暫停派發
                if is_system_overloaded(cpu_threshold=90.0, mem_threshold=90.0):
                    logger.warning(f"[Poller] System overloaded! Pausing task dispatch. Card {idx.card_id} waiting.")
                    continue

                logger.info(f"[Poller] Found pending card {idx.card_id} in {list_name}. Dispatching...")

                # 讀取 MD 檔並標記為 running 避免重複抓取
                project_path = project.path if project else "."
                card_data = _update_card_status(session, idx, "running", project_path)
                if card_data is None:
                    continue

                # 決定 Phase、Member 和 Provider（三層路由）
                phase = list_name.upper()
                member_id, forced_provider = _resolve_member(stage_list, phase, session)

                # 成員忙碌檢查：同一成員同時只能佔用一個工作台
                if member_id and member_id in busy_members:
                    logger.info(f"[Poller] Member {member_id} busy, skip card {idx.card_id}")
                    _update_card_status(session, idx, "pending", project_path)
                    continue

                project_name = project.name if project else "Unknown"
                card_title = idx.title

                # 使用 asyncio.create_task 在背景跑，這樣 poller 可以繼續掃描下一張卡片
                asyncio.create_task(_execute_and_update(
                    idx.card_id, project_path, card_data.content, phase,
                    card_title, project_name, forced_provider, member_id,
                    idx.project_id, str(idx.file_path),
                ))
            else:
                # 如果被拉到了不需要 AI 的列表 (如 Backlog 或 Done)，就把 pending 清掉
                project_path = project.path if project else "."
                _update_card_status(session, idx, "idle", project_path)

def _get_primary_provider(member_id: int, session) -> str | None:
    """從成員的主帳號（priority 最低）取得 provider"""
    from app.models.core import MemberAccount, Account
    binding = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id)
        .order_by(MemberAccount.priority)
    ).first()
    if binding:
        account = session.get(Account, binding.account_id)
        if account:
            return account.provider
    return None

def _resolve_member(stage_list, phase: str, session) -> tuple[int | None, str | None]:
    """三層路由：list 指派 → 全域預設 → None（由 runner PHASE_ROUTING 決定）
    回傳 (member_id, provider) tuple"""
    from app.models.core import Member

    # 1. 列表級指派
    if stage_list and stage_list.member_id:
        member = session.get(Member, stage_list.member_id)
        if member:
            provider = _get_primary_provider(member.id, session)
            logger.info(f"[Router] List '{stage_list.name}' assigned to {member.name} ({provider})")
            return member.id, provider

    # 2. 全域預設 (SystemSetting)
    setting = session.get(SystemSetting, f"phase_routing.{phase}")
    if setting and setting.value:
        try:
            member = session.get(Member, int(setting.value))
            if member:
                provider = _get_primary_provider(member.id, session)
                logger.info(f"[Router] Phase '{phase}' default → {member.name} ({provider})")
                return member.id, provider
        except (ValueError, TypeError):
            pass

    # 3. 由 runner.py PHASE_ROUTING 硬編碼決定
    return None, None


async def _execute_and_update(
    card_id: int, project_path: str, prompt: str, phase: str,
    card_title: str = "", project_name: str = "",
    forced_provider: str | None = None, member_id: int | None = None,
    project_id: int = 0, file_path_str: str = "",
):
    """包裝 run_ai_task，並在完成後更新 MD 檔案與資料庫卡片狀態"""
    result = await run_ai_task(card_id, project_path, prompt, phase, forced_provider=forced_provider, card_title=card_title, project_name=project_name, member_id=member_id)

    async with get_card_lock(card_id):
        file_path = Path(file_path_str) if file_path_str else card_file_path(project_path, card_id)

        with Session(engine) as session:
            # Read current MD file (may have been modified during execution)
            try:
                card_data = read_card(file_path)
            except Exception as e:
                logger.error(f"[Task {card_id}] Failed to read MD file after execution: {e}")
                # Fall back to ORM-only update
                card_data = None

            if result["status"] == "success":
                append_text = f"\n\n### AI Output ({result['provider']})\n```\n{result['output'][:1000]}...\n```"
                new_status = "completed"
            else:
                append_text = f"\n\n### Error ({result['provider']})\n{result['output']}"
                new_status = "failed"

            # Update MD file
            if card_data:
                card_data.content = card_data.content + append_text
                card_data.status = new_status
                write_card(file_path, card_data)
                sync_card_to_index(session, card_data, project_id, str(file_path))

            # Dual-write: keep Card ORM in sync during transition
            orm_card = session.get(Card, card_id)
            if orm_card:
                orm_card.content = (orm_card.content or "") + append_text
                orm_card.status = new_status
                session.add(orm_card)

            session.commit()
            logger.info(f"[Task {card_id}] State updated to {new_status}")

async def start_poller():
    """任務監聽器的主迴圈"""
    logger.info("Starting Aegis Task Poller...")
    while True:
        try:
            await _process_pending_cards()
        except Exception as e:
            logger.error(f"[Poller Error] {e}")
        
        # 每 3 秒掃描一次
        await asyncio.sleep(3)
