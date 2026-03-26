"""SQLite index cache management for MD card files."""
import json
import re
import hashlib
import logging
from pathlib import Path
from sqlmodel import Session, select, func
from app.models.core import CardIndex
from app.core.card_file import CardData, read_card, write_card

logger = logging.getLogger(__name__)

_PREFIX_RE = re.compile(r"^(feat|fix|docs|chore|refactor|test|style|perf|ci|build|revert)\s*[:：]\s*", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    """拆分中英文 token：英文用空格/標點分割，中文逐字。"""
    text = _PREFIX_RE.sub("", text).lower()
    tokens: set[str] = set()
    for part in re.split(r"[\s\-_/.,;:!?()（）、，。！？]+", text):
        if not part:
            continue
        buf = []
        for ch in part:
            if "\u4e00" <= ch <= "\u9fff":
                if buf:
                    tokens.add("".join(buf))
                    buf.clear()
                tokens.add(ch)
            else:
                buf.append(ch)
        if buf:
            tokens.add("".join(buf))
    tokens.discard("")
    return tokens


def title_similarity(a: str, b: str) -> float:
    """計算兩個標題的 Jaccard 相似度（移除常見前綴後）。"""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def block_similar_cards(card_id: int, title: str, session: Session) -> list[int]:
    """封鎖同 milestone 中標題相似的 idle/pending 卡片，回傳被封鎖的 card_id 列表。"""
    idx = session.get(CardIndex, card_id)
    if not idx:
        return []

    tags = json.loads(idx.tags_json) if idx.tags_json else []
    milestones = [t for t in tags if t.startswith("M")]
    if not milestones:
        return []

    # 查詢所有 idle/pending 的其他卡片
    stmt = select(CardIndex).where(
        CardIndex.card_id != card_id,
        CardIndex.status.in_(["idle", "pending"]),
    )
    candidates = list(session.exec(stmt).all())

    blocked_ids: list[int] = []
    for c in candidates:
        c_tags = json.loads(c.tags_json) if c.tags_json else []
        c_milestones = [t for t in c_tags if t.startswith("M")]
        if not set(milestones) & set(c_milestones):
            continue
        if title_similarity(title, c.title) < 0.6:
            continue

        # 加入 Blocked tag
        if "Blocked" not in c_tags:
            c_tags.append("Blocked")
            c.tags_json = json.dumps(c_tags, ensure_ascii=False)
            session.add(c)

            # 同步更新 MD 檔
            try:
                file_path = Path(c.file_path)
                if file_path.exists():
                    card_data = read_card(file_path)
                    if "Blocked" not in card_data.tags:
                        card_data.tags.append("Blocked")
                    write_card(file_path, card_data)
            except Exception as e:
                logger.warning(f"[Card {c.card_id}] Failed to update MD with Blocked tag: {e}")

        blocked_ids.append(c.card_id)

    return blocked_ids


def sync_card_to_index(
    session: Session,
    card: CardData,
    project_id: int,
    file_path: str,
    cron_job_id: int | None = None,
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
        existing.model = card.model
        existing.parent_id = card.parent_id
        existing.is_archived = card.is_archived
        existing.created_at = card.created_at
        existing.updated_at = card.updated_at
        existing.content_hash = content_hash
        existing.file_mtime = mtime
        if cron_job_id is not None:
            existing.cron_job_id = cron_job_id
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
            model=card.model,
            parent_id=card.parent_id,
            is_archived=card.is_archived,
            created_at=card.created_at,
            updated_at=card.updated_at,
            content_hash=content_hash,
            file_mtime=mtime,
            cron_job_id=cron_job_id,
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
