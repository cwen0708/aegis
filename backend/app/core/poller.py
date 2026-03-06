import asyncio
import logging
from sqlmodel import Session, select
from app.database import engine
from app.models.core import Card, StageList, SystemSetting
from app.core.runner import run_ai_task, busy_members
from app.core.telemetry import is_system_overloaded

logger = logging.getLogger(__name__)

# 全域暫停旗標，供 API 控制
is_paused = False

async def _process_pending_cards():
    """定期掃描資料庫中 status='pending' 的卡片並派發給 AI"""
    if is_paused:
        return

    with Session(engine) as session:
        # 找出狀態為 pending，並且身處在需要 AI 介入的列表 (Planning 或 Developing)
        # 這裡為了簡單示範，我們抓取所有 pending 卡片
        pending_cards = session.exec(
            select(Card).where(Card.status == "pending")
        ).all()

        for card in pending_cards:
            list_name = card.stage_list.name if card.stage_list else "Unknown"
            
            # 只有特定的列表才需要喚醒 AI
            if list_name in ["Planning", "Developing", "Verifying", "Scheduled"]:

                # 防護機制：如果系統負載過高，暫停派發
                if is_system_overloaded(cpu_threshold=90.0, mem_threshold=90.0):
                    logger.warning(f"[Poller] System overloaded! Pausing task dispatch. Card {card.id} waiting.")
                    continue

                logger.info(f"[Poller] Found pending card {card.id} in {list_name}. Dispatching...")

                # 標記為 running 避免重複抓取
                card.status = "running"
                session.add(card)
                session.commit()

                # 決定 Phase、Member 和 Provider（三層路由）
                phase = list_name.upper()
                member_id, forced_provider = _resolve_member(card.stage_list, phase, session)

                # 成員忙碌檢查：同一成員同時只能佔用一個工作台
                if member_id and member_id in busy_members:
                    logger.info(f"[Poller] Member {member_id} busy, skip card {card.id}")
                    card.status = "pending"  # 保持 pending，下次 poll 再試
                    session.add(card)
                    session.commit()
                    continue

                project_path = card.stage_list.project.path if card.stage_list and card.stage_list.project else "."
                project_name = card.stage_list.project.name if card.stage_list and card.stage_list.project else "Unknown"
                card_title = card.title

                # 使用 asyncio.create_task 在背景跑，這樣 poller 可以繼續掃描下一張卡片
                asyncio.create_task(_execute_and_update(card.id, project_path, card.content, phase, card_title, project_name, forced_provider, member_id))
            else:
                # 如果被拉到了不需要 AI 的列表 (如 Backlog 或 Done)，就把 pending 清掉
                card.status = "idle"
                session.add(card)
                session.commit()

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


async def _execute_and_update(card_id: int, project_path: str, prompt: str, phase: str, card_title: str = "", project_name: str = "", forced_provider: str | None = None, member_id: int | None = None):
    """包裝 run_ai_task，並在完成後更新資料庫卡片狀態"""
    result = await run_ai_task(card_id, project_path, prompt, phase, forced_provider=forced_provider, card_title=card_title, project_name=project_name, member_id=member_id)
    
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card:
            if result["status"] == "success":
                # 把 AI 的輸出寫進卡片裡 (實務上可能會寫到 comments 或專門的 log 欄位)
                card.content = card.content + f"\n\n### AI Output ({result['provider']})\n```\n{result['output'][:1000]}...\n```"
                card.status = "completed"
                # 這裡可以根據 phase 自動將卡片移到下一個 list (如 Planning -> Developing)
            else:
                card.content = card.content + f"\n\n### Error ({result['provider']})\n{result['output']}"
                card.status = "failed"
                
            session.add(card)
            session.commit()
            logger.info(f"[Task {card_id}] State updated to {card.status}")

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
