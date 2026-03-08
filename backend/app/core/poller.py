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
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.memory_manager import write_member_short_term_memory

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

                # 決定 Phase、Member 和 Provider（三層路由）
                phase = list_name.upper()
                member_id, forced_provider = _resolve_member(stage_list, phase, session)

                # 成員忙碌檢查：先檢查再標記，避免不必要的 pending→running→pending 狀態翻轉
                if member_id and member_id in busy_members:
                    logger.info(f"[Poller] Member {member_id} busy, skip card {idx.card_id}")
                    continue

                # 讀取 MD 檔並標記為 running 避免重複抓取
                project_path = project.path if project else "."
                card_data = _update_card_status(session, idx, "running", project_path)
                if card_data is None:
                    continue

                project_name = project.name if project else "Unknown"
                card_title = idx.title

                # 建立臨時工作區（有指派角色時）
                workspace_dir = None
                member_slug = None
                if member_id:
                    from app.models.core import Member as MemberModel
                    member_obj = session.get(MemberModel, member_id)
                    if member_obj and member_obj.slug:
                        member_slug = member_obj.slug
                        workspace_dir = str(prepare_workspace(
                            card_id=idx.card_id,
                            member_slug=member_slug,
                            provider=forced_provider or "claude",
                            project_path=project_path,
                            card_content=card_data.content,
                        ))

                # 使用 asyncio.create_task 在背景跑，這樣 poller 可以繼續掃描下一張卡片
                asyncio.create_task(_execute_and_update(
                    idx.card_id, project_path, card_data.content, phase,
                    card_title, project_name, forced_provider, member_id,
                    idx.project_id, str(idx.file_path),
                    workspace_dir=workspace_dir, member_slug=member_slug,
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


async def _notify_channels(card_id: int, card_title: str, project_name: str,
                          status: str, result: dict):
    """發送任務完成通知到已綁定的頻道"""
    from app.channels.bus import message_bus
    from app.channels.types import OutboundMessage
    from app.database import engine
    from app.models.core import ChannelBinding
    from sqlmodel import Session, select

    try:
        # 查詢此專案綁定的頻道
        with Session(engine) as session:
            bindings = session.exec(
                select(ChannelBinding).where(
                    ChannelBinding.entity_type == "project",
                    ChannelBinding.notify_on_complete == True
                )
            ).all()

            if not bindings:
                return

            # 格式化通知訊息
            emoji = "✅" if status == "completed" else "❌"
            output_preview = result.get("output", "")[:200]
            text = (
                f"{emoji} **任務{status}**\n"
                f"📋 {card_title}\n"
                f"📁 {project_name}\n"
                f"```\n{output_preview}...\n```"
            )

            # 發送到每個綁定的頻道
            for binding in bindings:
                msg = OutboundMessage(
                    chat_id=binding.chat_id,
                    text=text,
                    platform=binding.platform,
                    card_id=card_id,
                )
                await message_bus.publish_outbound(msg)
                logger.info(f"[Notify] Sent to {binding.platform}:{binding.chat_id}")

    except Exception as e:
        logger.warning(f"[Notify] Failed to send channel notification: {e}")


async def _execute_and_update(
    card_id: int, project_path: str, prompt: str, phase: str,
    card_title: str = "", project_name: str = "",
    forced_provider: str | None = None, member_id: int | None = None,
    project_id: int = 0, file_path_str: str = "",
    workspace_dir: str | None = None, member_slug: str | None = None,
):
    """包裝 run_ai_task，並在完成後更新 MD 檔案與資料庫卡片狀態"""
    from app.core.ws_manager import broadcast_event

    try:
        # 有工作區時，cwd 用工作區；prompt 簡化為指示讀取 config
        effective_cwd = workspace_dir or project_path
        effective_prompt = "請閱讀你的設定檔並執行本次任務。" if workspace_dir else prompt

        result = await run_ai_task(card_id, effective_cwd, effective_prompt, phase, forced_provider=forced_provider, card_title=card_title, project_name=project_name, member_id=member_id)

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

        # 在 index 更新並 commit 之後才廣播，避免前端刷看板時拿到舊狀態
        event = "task_completed" if new_status == "completed" else "task_failed"
        await broadcast_event(event, {"card_id": card_id, "status": new_status})

        # 發送頻道通知（如有啟用）
        await _notify_channels(card_id, card_title, project_name, new_status, result)

        # 寫入角色短期記憶
        if member_slug:
            try:
                status_text = result.get("status", "unknown")
                output_preview = result.get("output", "")[:500]
                write_member_short_term_memory(
                    member_slug,
                    f"## 任務: {card_title}\n專案: {project_name}\n結果: {status_text}\n\n{output_preview}"
                )
            except Exception as e:
                logger.warning(f"[Memory] Failed to write member memory: {e}")

    except Exception as e:
        # 錯誤回復：確保卡片不會永遠卡在 running 狀態
        logger.exception(f"[Task {card_id}] _execute_and_update failed: {e}")
        try:
            async with get_card_lock(card_id):
                file_path = Path(file_path_str) if file_path_str else card_file_path(project_path, card_id)
                with Session(engine) as session:
                    try:
                        card_data = read_card(file_path)
                        card_data.status = "failed"
                        card_data.content = card_data.content + f"\n\n### Error\n內部錯誤: {e}"
                        write_card(file_path, card_data)
                        sync_card_to_index(session, card_data, project_id, str(file_path))
                    except Exception:
                        pass
                    orm_card = session.get(Card, card_id)
                    if orm_card:
                        orm_card.status = "failed"
                        session.add(orm_card)
                    session.commit()
            await broadcast_event("task_failed", {"card_id": card_id, "reason": str(e)})
        except Exception as inner_e:
            logger.error(f"[Task {card_id}] Failed to recover card state: {inner_e}")

    finally:
        # 確保臨時工作區一定被清理
        if workspace_dir:
            cleanup_workspace(card_id)

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
