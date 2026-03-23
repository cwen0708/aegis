"""
統一卡片建立工廠 — 避免多處重複 CardData 建構 + write + sync 邏輯
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select, func

from app.core.card_file import CardData, card_file_path, write_card
from app.core.card_index import sync_card_to_index
from app.database import engine

logger = logging.getLogger(__name__)


def _get_next_card_id(session: Session) -> int:
    """取得下一個可用的 card_id（全域最大值 +1）"""
    from app.models.core import CardIndex
    max_id = session.exec(select(func.max(CardIndex.card_id))).one() or 0
    return max_id + 1


def _get_project_path(session: Session, project_id: int) -> Optional[str]:
    """從 DB 取得專案路徑"""
    from app.models.core import Project
    project = session.get(Project, project_id)
    return project.path if project else None


def create_card(
    project_id: int,
    list_id: int,
    title: str,
    content: str = "",
    description: Optional[str] = None,
    status: str = "idle",
    tags: Optional[list[str]] = None,
) -> Optional[CardData]:
    """建立卡片（MD 檔 + CardIndex），回傳 CardData 或 None

    這是最底層的共用函式，所有卡片建立都應走這裡。
    """
    try:
        with Session(engine) as session:
            project_path = _get_project_path(session, project_id)
            if not project_path:
                logger.warning(f"[CardFactory] Project {project_id} not found")
                return None

            card_id = _get_next_card_id(session)
            now = datetime.now(timezone.utc)

            card = CardData(
                id=card_id,
                list_id=list_id,
                title=title,
                description=description,
                content=content,
                status=status,
                tags=tags or [],
                is_archived=False,
                created_at=now,
                updated_at=now,
            )

            fpath = card_file_path(project_path, card_id)
            fpath.parent.mkdir(parents=True, exist_ok=True)
            write_card(fpath, card)
            sync_card_to_index(session, card, project_id=project_id, file_path=str(fpath))

            logger.info(f"[CardFactory] Created #{card_id}: {title[:50]}")
            return card
    except Exception as e:
        logger.error(f"[CardFactory] Failed to create card: {e}")
        return None


def create_chat_card(
    project_id: int,
    member_id: int,
    chat_id: str,
    message: str,
    history: str = "",
) -> Optional[CardData]:
    """建立 [chat] 卡片到成員收件匣

    自動查詢成員的 AI stage list，組裝 chat_id metadata。
    """
    try:
        with Session(engine) as session:
            from app.models.core import StageList
            # 找成員的 AI stage
            inbox = session.exec(
                select(StageList).where(
                    StageList.project_id == project_id,
                    StageList.member_id == member_id,
                    StageList.is_ai_stage == True,
                )
            ).first()
            if not inbox:
                logger.warning(f"[CardFactory] No AI inbox for member {member_id}")
                return None

            member_slug = chat_id.split(":")[-1] if ":" in chat_id else "unknown"
            content = f"<!-- chat_id: {chat_id} -->\n"
            if history:
                content += f"{history}\n"
            content += f"## 用戶訊息\n\n{message}"

            return create_card(
                project_id=project_id,
                list_id=inbox.id,
                title=f"[chat] {member_slug}: {message[:30]}",
                content=content,
                status="pending",
            )
    except Exception as e:
        logger.error(f"[CardFactory] Failed to create chat card: {e}")
        return None
