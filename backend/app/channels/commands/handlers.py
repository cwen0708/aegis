"""
命令處理器 — 執行業務邏輯並產生回應
"""
from typing import Optional
from sqlmodel import Session, select
from .parser import ParsedCommand, CommandType, get_help_text
from ..types import InboundMessage
from app.database import engine
from app.models.core import Card, StageList, Project
import logging

logger = logging.getLogger(__name__)


async def handle_command(cmd: ParsedCommand, msg: InboundMessage) -> Optional[str]:
    """
    處理命令並返回回應文字

    Args:
        cmd: 解析後的命令
        msg: 原始訊息（用於取得用戶資訊）

    Returns:
        回應文字，或 None（不需要回應）
    """
    handler_map = {
        CommandType.CARD_CREATE: _handle_card_create,
        CommandType.CARD_LIST: _handle_card_list,
        CommandType.CARD_VIEW: _handle_card_view,
        CommandType.TASK_RUN: _handle_task_run,
        CommandType.TASK_STOP: _handle_task_stop,
        CommandType.TASK_STATUS: _handle_task_status,
        CommandType.STATUS: _handle_status,
        CommandType.HELP: _handle_help,
    }

    handler = handler_map.get(cmd.cmd_type)
    if handler:
        try:
            return await handler(cmd, msg)
        except Exception as e:
            logger.error(f"Command handler error: {e}", exc_info=True)
            return f"❌ 執行失敗: {str(e)[:100]}"

    return "❓ 未知命令，輸入 /help 查看說明"


# ===== 卡片命令 =====

async def _handle_card_create(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """建立新卡片"""
    title = cmd.args[0] if cmd.args else "新卡片"

    # 清理輸入
    title = title.strip()[:200]
    if not title:
        return "❌ 標題不可為空"

    with Session(engine) as session:
        # 找預設專案的 Backlog
        project = session.exec(
            select(Project).where(Project.is_system == False)
        ).first()

        if not project:
            return "❌ 找不到可用專案"

        backlog = session.exec(
            select(StageList).where(
                StageList.project_id == project.id,
                StageList.name == "Backlog"
            )
        ).first()

        if not backlog:
            return "❌ 找不到 Backlog 列表"

        card = Card(
            list_id=backlog.id,
            title=title,
            description=f"由 {msg.platform} 用戶 {msg.user_name or msg.user_id} 建立",
            status="idle",
        )
        session.add(card)
        session.commit()
        session.refresh(card)

        return (
            f"✅ 卡片 #{card.id} 已建立\n"
            f"📋 {title}\n"
            f"📁 {project.name} / Backlog"
        )


async def _handle_card_list(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """列出最近卡片"""
    with Session(engine) as session:
        cards = session.exec(
            select(Card).order_by(Card.updated_at.desc()).limit(10)
        ).all()

        if not cards:
            return "📭 目前沒有卡片"

        lines = ["📋 *最近卡片*\n"]
        status_icons = {
            "idle": "⚪",
            "pending": "🟡",
            "running": "🔵",
            "done": "✅",
            "failed": "❌",
        }

        for c in cards:
            icon = status_icons.get(c.status, "⚪")
            lines.append(f"{icon} #{c.id} {c.title[:30]}")

        return "\n".join(lines)


async def _handle_card_view(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """查看卡片詳情"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        status_text = {
            "idle": "閒置",
            "pending": "等待中",
            "running": "執行中",
            "done": "完成",
            "failed": "失敗",
        }.get(card.status, card.status)

        return (
            f"📋 *卡片 #{card.id}*\n\n"
            f"*標題*: {card.title}\n"
            f"*狀態*: {status_text}\n"
            f"*描述*: {card.description or '(無)'}\n\n"
            f"執行: /run {card.id}"
        )


# ===== 任務命令 =====

async def _handle_task_run(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """執行任務"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        if card.status == "running":
            return f"⚠️ 卡片 #{card_id} 已在執行中"

        # 更新狀態為 pending
        card.status = "pending"
        session.add(card)
        session.commit()

    # TODO: 觸發實際任務執行（透過現有 runner 機制）
    return f"🚀 卡片 #{card_id} 已加入執行佇列"


async def _handle_task_stop(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """中止任務"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        if card.status != "running":
            return f"⚠️ 卡片 #{card_id} 未在執行中"

    # TODO: 觸發實際任務中止
    return f"🛑 已請求中止卡片 #{card_id}"


async def _handle_task_status(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """查看任務狀態"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        status_emoji = {
            "idle": "⚪",
            "pending": "🟡",
            "running": "🔵",
            "done": "✅",
            "failed": "❌",
        }

        return (
            f"{status_emoji.get(card.status, '❓')} 卡片 #{card.id}\n"
            f"*{card.title}*\n"
            f"狀態: {card.status}"
        )


# ===== 系統命令 =====

async def _handle_status(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """系統狀態"""
    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    with Session(engine) as session:
        running_count = session.exec(
            select(Card).where(Card.status == "running")
        ).all()
        pending_count = session.exec(
            select(Card).where(Card.status == "pending")
        ).all()

    return (
        f"📊 *Aegis 系統狀態*\n\n"
        f"🖥️ CPU: {cpu}%\n"
        f"💾 RAM: {mem.percent}%\n"
        f"🔵 執行中: {len(running_count)}\n"
        f"🟡 等待中: {len(pending_count)}"
    )


async def _handle_help(cmd: ParsedCommand, msg: InboundMessage) -> str:
    """顯示說明"""
    return get_help_text()
