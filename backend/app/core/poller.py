import asyncio
import logging
import re
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session, select
from app.database import engine
from app.models.core import Card, CardIndex, StageList, Project, SystemSetting, Member
from app.core.card_file import CardData, read_card, write_card, card_file_path
from app.core.card_index import sync_card_to_index, query_pending_cards, next_card_id
from app.core.runner import run_ai_task, busy_members
from app.core.telemetry import is_system_overloaded
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.memory_manager import write_member_short_term_memory

logger = logging.getLogger(__name__)

# DEBUG ring buffer for remote log viewing
debug_log: deque[str] = deque(maxlen=200)

def dprint(msg: str):
    """Print + store in ring buffer for API access."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    debug_log.append(line)

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

            # DEBUG: 追蹤 pending 卡片的路由決策
            dprint(f"[Poller DEBUG] Card {idx.card_id}: list_id={idx.list_id}, "
                  f"stage_list={'found' if stage_list else 'NOT FOUND'}, "
                  f"project_id={idx.project_id}, file_path={idx.file_path}")
            if stage_list:
                dprint(f"[Poller DEBUG] Card {idx.card_id}: stage_list.name={stage_list.name}, "
                      f"is_ai_stage={stage_list.is_ai_stage}, stage_type={stage_list.stage_type}, "
                      f"member_id={stage_list.member_id}")

            # 判斷此階段是否需要 AI 處理
            # 根據 stage_type 和 is_ai_stage 決定（通用化工作流）
            should_ai_process = (
                stage_list
                and stage_list.is_ai_stage
                and stage_list.stage_type in ["auto_process", "auto_review"]
            )

            dprint(f"[Poller DEBUG] Card {idx.card_id}: should_ai_process={should_ai_process}")

            if should_ai_process:

                # 防護機制：如果系統負載過高，暫停派發
                if is_system_overloaded(cpu_threshold=90.0, mem_threshold=90.0):
                    dprint(f"[Poller DEBUG] Card {idx.card_id}: SYSTEM OVERLOADED, skipping")
                    continue

                dprint(f"[Poller DEBUG] Card {idx.card_id}: dispatching (AI stage)")

                # 決定 Phase、Member 和 Provider（三層路由）
                # phase 用於向後相容，從列表名稱推導
                phase = list_name.upper() if list_name else "DEVELOPING"
                member_id, forced_provider = _resolve_member(stage_list, project, phase, session)
                dprint(f"[Poller DEBUG] Card {idx.card_id}: member_id={member_id}, provider={forced_provider}, busy_members={list(busy_members)}")

                # 成員忙碌檢查：先檢查再標記，避免不必要的 pending→running→pending 狀態翻轉
                if member_id and member_id in busy_members:
                    dprint(f"[Poller DEBUG] Card {idx.card_id}: MEMBER BUSY, skipping")
                    continue

                # 讀取 MD 檔並標記為 running 避免重複抓取
                project_path = project.path if project else "."
                card_data = _update_card_status(session, idx, "running", project_path)
                dprint(f"[Poller DEBUG] Card {idx.card_id}: _update_card_status returned {'OK' if card_data else 'None'}")
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
                # 非 AI 處理階段（manual, terminal 或 is_ai_stage=False），清除 pending 狀態
                dprint(f"[Poller DEBUG] Card {idx.card_id}: RESETTING TO IDLE (not AI stage)")
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

def _resolve_member(stage_list, project, phase: str, session) -> tuple[int | None, str | None]:
    """三層路由：列表指派 → 專案預設 → 全域預設
    回傳 (member_id, provider) tuple"""
    from app.models.core import Member

    # 1. 列表級指派
    if stage_list and stage_list.member_id:
        member = session.get(Member, stage_list.member_id)
        if member:
            provider = _get_primary_provider(member.id, session)
            logger.info(f"[Router] List '{stage_list.name}' assigned → {member.name} ({provider})")
            return member.id, provider

    # 2. 專案預設成員
    if project and project.default_member_id:
        member = session.get(Member, project.default_member_id)
        if member:
            provider = _get_primary_provider(member.id, session)
            logger.info(f"[Router] Project '{project.name}' default → {member.name} ({provider})")
            return member.id, provider

    # 3. 全域預設 (SystemSetting)
    setting = session.get(SystemSetting, f"phase_routing.{phase}")
    if setting and setting.value:
        try:
            member = session.get(Member, int(setting.value))
            if member:
                provider = _get_primary_provider(member.id, session)
                logger.info(f"[Router] Phase '{phase}' global default → {member.name} ({provider})")
                return member.id, provider
        except (ValueError, TypeError):
            pass

    # 無路由，使用第一個可用成員
    return None, None


def _parse_and_create_cards(
    output: str, project_id: int, project_path: str, session: Session,
    member_slug: str | None = None, source_card_id: int | None = None,
) -> list[int]:
    """解析 AI 輸出中的 create_cards 區塊，自動建立卡片

    AI 可在輸出中使用以下格式建立新卡片：
    ```json:create_cards
    [
      {"title": "卡片標題", "list_name": "待處置", "content": "卡片內容..."},
      {"title": "求助", "list_name": "待處置", "content": "...",
       "target_member": "xiao-jun", "target_project": "aegis"}
    ]
    ```

    跨成員協作欄位（可選）：
    - target_member: 指定成員 slug，卡片會建到該成員負責的 list
    - target_project: 指定專案名稱（跨專案協作時使用）

    Returns: 新建卡片的 ID 列表
    """
    # 匹配 ```json:create_cards ... ```
    pattern = r'```json:create_cards\s*\n(.*?)\n```'
    matches = re.findall(pattern, output, re.DOTALL)

    if not matches:
        return []

    created_ids = []
    for match in matches:
        try:
            cards_data = json.loads(match)
            if not isinstance(cards_data, list):
                cards_data = [cards_data]

            for card_info in cards_data:
                title = card_info.get("title", "").strip()
                list_name = card_info.get("list_name", "").strip()
                content = card_info.get("content", "")
                target_member = card_info.get("target_member", "").strip()
                target_project = card_info.get("target_project", "").strip()

                if not title or not list_name:
                    logger.warning(f"[CreateCard] Missing title or list_name: {card_info}")
                    continue

                # ── 跨成員協作：解析 target_member ──
                effective_project_id = project_id
                effective_project_path = project_path
                tags: list[str] = []
                target_list_id: int | None = None

                if target_member:
                    # 防循環：不能自己指派自己
                    if target_member == member_slug:
                        logger.warning(f"[CreateCard] Self-targeting blocked: {target_member}")
                        continue

                    member = session.exec(
                        select(Member).where(Member.slug == target_member)
                    ).first()
                    if not member:
                        logger.warning(f"[CreateCard] Target member '{target_member}' not found")
                        continue

                    # 跨專案：查找目標專案
                    if target_project:
                        proj = session.exec(
                            select(Project).where(Project.name == target_project)
                        ).first()
                        if proj:
                            effective_project_id = proj.id
                            effective_project_path = proj.path
                        else:
                            logger.warning(f"[CreateCard] Target project '{target_project}' not found, using current")

                    # 找目標成員在目標專案中負責的 StageList
                    member_list = session.exec(
                        select(StageList).where(
                            StageList.project_id == effective_project_id,
                            StageList.member_id == member.id,
                            StageList.is_ai_stage == True,
                        )
                    ).first()
                    if member_list:
                        target_list_id = member_list.id
                    else:
                        # fallback: 第一個 auto_process list
                        fallback_list = session.exec(
                            select(StageList).where(
                                StageList.project_id == effective_project_id,
                                StageList.stage_type == "auto_process",
                            )
                        ).first()
                        if fallback_list:
                            target_list_id = fallback_list.id

                    if not target_list_id:
                        logger.warning(f"[CreateCard] No suitable list for member '{target_member}' in project {effective_project_id}")
                        continue

                    # 加上協作 tags
                    tags.append("collab:request")
                    if member_slug:
                        tags.append(f"collab:from:{member_slug}")
                    if source_card_id:
                        tags.append(f"collab:ref:{source_card_id}")

                    logger.info(f"[Collab] {member_slug} → {target_member}: {title}")

                # 查找對應的 StageList（非協作卡片走原本邏輯）
                if target_list_id:
                    final_list_id = target_list_id
                else:
                    stage_list = session.exec(
                        select(StageList).where(
                            StageList.project_id == effective_project_id,
                            StageList.name == list_name
                        )
                    ).first()
                    if not stage_list:
                        logger.warning(f"[CreateCard] List '{list_name}' not found in project {effective_project_id}")
                        continue
                    final_list_id = stage_list.id

                # 取得下一個卡片 ID
                new_card_id = next_card_id(session)

                # 建立 CardData
                card_data = CardData(
                    id=new_card_id,
                    title=title,
                    status="idle",
                    list_id=final_list_id,
                    content=content,
                    tags=tags,
                )

                # 寫入 MD 檔案
                file_path = card_file_path(effective_project_path, new_card_id)
                write_card(file_path, card_data)

                # 同步到索引
                sync_card_to_index(session, card_data, effective_project_id, str(file_path))

                created_ids.append(new_card_id)
                logger.info(f"[CreateCard] Created card {new_card_id}: {title} → list_id={final_list_id}")

        except json.JSONDecodeError as e:
            logger.warning(f"[CreateCard] Failed to parse JSON: {e}")
        except Exception as e:
            logger.warning(f"[CreateCard] Error creating card: {e}")

    if created_ids:
        session.commit()
        logger.info(f"[CreateCard] Total {len(created_ids)} cards created: {created_ids}")

    return created_ids


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


def _handle_collab_feedback(
    card_id: int, card_data: CardData | None, result: dict, session: Session,
    project_path: str, project_id: int,
):
    """協作卡片完成後，回報結果給原始請求者"""
    if not card_data or not card_data.tags:
        return

    # 解析協作 tags
    requester_slug = None
    ref_card_id = None
    for tag in card_data.tags:
        if tag.startswith("collab:from:"):
            requester_slug = tag[len("collab:from:"):]
        elif tag.startswith("collab:ref:"):
            try:
                ref_card_id = int(tag[len("collab:ref:"):])
            except ValueError:
                pass

    if not requester_slug:
        return

    status_text = result.get("status", "unknown")
    output_preview = result.get("output", "")[:500]

    # 1. 寫入請求者的短期記憶
    try:
        write_member_short_term_memory(
            requester_slug,
            f"## 協作結果\n"
            f"你請求協助的問題已完成。\n"
            f"協助卡片: #{card_id} — {card_data.title}\n"
            f"{'原始卡片: #' + str(ref_card_id) if ref_card_id else ''}\n"
            f"結果: {status_text}\n\n{output_preview}"
        )
        logger.info(f"[Collab] Feedback written to {requester_slug}'s memory")
    except Exception as e:
        logger.warning(f"[Collab] Failed to write feedback memory: {e}")

    # 2. 在原始卡片追加更新紀錄
    if ref_card_id:
        try:
            ref_file = card_file_path(project_path, ref_card_id)
            if ref_file.exists():
                ref_card = read_card(ref_file)
                brief = output_preview[:200].replace("\n", " ")
                ref_card.content += f"\n\n### 協作更新\n協助卡片 #{card_id} 已完成（{status_text}）：{brief}"
                write_card(ref_file, ref_card)
                sync_card_to_index(session, ref_card, project_id, str(ref_file))
                logger.info(f"[Collab] Updated ref card #{ref_card_id} with collaboration result")
        except Exception as e:
            logger.warning(f"[Collab] Failed to update ref card #{ref_card_id}: {e}")


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

        dprint(f"[Exec DEBUG] Card {card_id}: starting run_ai_task, cwd={effective_cwd}, member_id={member_id}")
        result = await run_ai_task(card_id, effective_cwd, effective_prompt, phase, forced_provider=forced_provider, card_title=card_title, project_name=project_name, member_id=member_id)
        dprint(f"[Exec DEBUG] Card {card_id}: run_ai_task returned status={result.get('status')}")

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

                # 解析 AI 輸出中的 create_cards 區塊，自動建立新卡片
                # completed 和 failed 都解析（失敗時 AI 可能發出協作求助）
                is_collab_card = card_data and any(t.startswith("collab:") for t in card_data.tags)
                if not is_collab_card:  # 防循環：協作卡片不能再觸發新協作
                    created_card_ids = _parse_and_create_cards(
                        result.get("output", ""),
                        project_id,
                        project_path,
                        session,
                        member_slug=member_slug,
                        source_card_id=card_id,
                    )
                    if created_card_ids:
                        logger.info(f"[Task {card_id}] AI auto-created {len(created_card_ids)} cards")

                # 協作回饋：如果這張卡是別人請求協助的，完成後通知請求者
                if is_collab_card:
                    _handle_collab_feedback(card_id, card_data, result, session, project_path, project_id)

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
        dprint(f"[Exec DEBUG] Card {card_id}: EXCEPTION in _execute_and_update: {e}")
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
    dprint("[Poller] Starting Aegis Task Poller...")
    cycle = 0
    while True:
        try:
            cycle += 1
            if cycle % 20 == 1:  # 每 60 秒記一次 heartbeat
                dprint(f"[Poller] heartbeat cycle={cycle}")
            await _process_pending_cards()
        except Exception as e:
            dprint(f"[Poller] ERROR: {e}")
            logger.error(f"[Poller Error] {e}")

        # 每 3 秒掃描一次
        await asyncio.sleep(3)
