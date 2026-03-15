"""SQLite index cache management for MD card files."""
import json
import hashlib
import logging
from pathlib import Path
from sqlmodel import Session, select, func
from app.models.core import CardIndex
from app.core.card_file import CardData, read_card

logger = logging.getLogger(__name__)


def sync_card_to_index(
    session: Session,
    card: CardData,
    project_id: int,
    file_path: str,
) -> None:
    """Upsert a single card's metadata into the index."""
    fpath = Path(file_path)
    mtime = fpath.stat().st_mtime if fpath.exists() else 0.0
    content_hash = hashlib.sha256(fpath.read_bytes()).hexdigest() if fpath.exists() else ""
    tags_json = json.dumps(card.tags, ensure_ascii=False)

    existing = session.get(CardIndex, card.id)
    if existing:
        existing.project_id = project_id
        existing.file_path = file_path
        existing.list_id = card.list_id
        existing.status = card.status
        existing.title = card.title
        existing.description = card.description
        existing.tags_json = tags_json
        existing.is_archived = card.is_archived
        existing.created_at = card.created_at
        existing.updated_at = card.updated_at
        existing.content_hash = content_hash
        existing.file_mtime = mtime
        session.add(existing)
    else:
        idx = CardIndex(
            card_id=card.id,
            project_id=project_id,
            file_path=file_path,
            list_id=card.list_id,
            status=card.status,
            title=card.title,
            description=card.description,
            tags_json=tags_json,
            is_archived=card.is_archived,
            created_at=card.created_at,
            updated_at=card.updated_at,
            content_hash=content_hash,
            file_mtime=mtime,
        )
        session.add(idx)


def remove_card_from_index(session: Session, card_id: int) -> None:
    """Remove a card from the index."""
    idx = session.get(CardIndex, card_id)
    if idx:
        session.delete(idx)


def query_pending_cards(session: Session, project_id: int = None) -> list[CardIndex]:
    """Query cards with status='pending'."""
    stmt = select(CardIndex).where(CardIndex.status == "pending")
    if project_id is not None:
        stmt = stmt.where(CardIndex.project_id == project_id)
    return list(session.exec(stmt).all())


def query_board(session: Session, project_id: int) -> list[CardIndex]:
    """Query non-archived cards for a project (for board display)."""
    stmt = select(CardIndex).where(
        CardIndex.project_id == project_id,
        CardIndex.is_archived == False  # noqa: E712
    )
    return list(session.exec(stmt).all())


def query_archived(session: Session, project_id: int) -> list[CardIndex]:
    """Query archived cards for a project."""
    stmt = select(CardIndex).where(
        CardIndex.project_id == project_id,
        CardIndex.is_archived == True  # noqa: E712
    ).order_by(CardIndex.updated_at.desc())
    return list(session.exec(stmt).all())


def rebuild_index(session: Session, project_id: int, project_path: str) -> int:
    """Scan all MD files in project and rebuild index. Returns card count."""
    cards_dir = Path(project_path) / ".aegis" / "cards"
    if not cards_dir.exists():
        return 0

    count = 0
    for md_file in sorted(cards_dir.glob("card-*.md")):
        try:
            card = read_card(md_file)
            sync_card_to_index(session, card, project_id, str(md_file))
            count += 1
        except (ValueError, Exception) as e:
            logger.warning(f"Skipping {md_file}: {e}")
    return count


def next_card_id(session: Session) -> int:
    """Get next available global card ID (never reuses deleted IDs).

    Checks both CardIndex and TaskLog to find the true max,
    preventing ID collision when cron cards are deleted.
    """
    from app.models.core import TaskLog
    idx_max = session.exec(select(func.max(CardIndex.card_id))).first() or 0
    log_max = session.exec(select(func.max(TaskLog.card_id))).first() or 0
    return max(idx_max, log_max) + 1
