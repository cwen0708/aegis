"""MD file read/write engine for card data."""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

VALID_STATUSES = {"idle", "pending", "running", "completed", "failed"}

# 內部寫入抑制：write_card() 寫入前註冊路徑，watcher 檢查後消耗
# 使用計數器而非 set，避免兩次快速寫入只消耗一次標記
_internal_writes: dict[str, int] = {}


def mark_internal_write(path: Path) -> None:
    """標記路徑為內部寫入（抑制 watcher 重複處理）。"""
    resolved = str(path.resolve())
    _internal_writes[resolved] = _internal_writes.get(resolved, 0) + 1


def consume_internal_write(path: Path) -> bool:
    """若路徑曾被標記為內部寫入，消耗一次標記並回傳 True。"""
    resolved = str(path.resolve())
    count = _internal_writes.get(resolved, 0)
    if count > 0:
        if count == 1:
            del _internal_writes[resolved]
        else:
            _internal_writes[resolved] = count - 1
        return True
    return False


@dataclass
class CardData:
    """Card data structure (independent of SQLModel ORM)."""
    id: int
    list_id: int
    title: str
    description: Optional[str]
    content: str
    status: str
    tags: list[str] = field(default_factory=list)
    is_archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def card_file_path(project_path: str, card_id: int) -> Path:
    """Return path: {project_path}/.aegis/cards/card-{id:06d}.md"""
    return Path(project_path) / ".aegis" / "cards" / f"card-{card_id:06d}.md"


def serialize_card(card: CardData) -> str:
    """Serialize CardData to frontmatter + markdown body string."""
    metadata = {
        "id": card.id,
        "list_id": card.list_id,
        "title": card.title,
        "description": card.description,
        "status": card.status,
        "tags": card.tags,
        "is_archived": card.is_archived,
        "created_at": card.created_at.isoformat(),
        "updated_at": card.updated_at.isoformat(),
    }
    post = frontmatter.Post(card.content, **metadata)
    return frontmatter.dumps(post) + "\n"


def write_card(file_path: Path, card: CardData) -> None:
    """Atomic write: temp -> fsync -> rename."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    mark_internal_write(file_path)
    try:
        tmp = file_path.with_suffix(".md.tmp")
        content = serialize_card(card)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(file_path)
    except Exception:
        # 寫入失敗時回退計數器，避免永久殘留
        resolved = str(file_path.resolve())
        count = _internal_writes.get(resolved, 0)
        if count <= 1:
            _internal_writes.pop(resolved, None)
        else:
            _internal_writes[resolved] = count - 1
        raise


def read_card(file_path: Path) -> CardData:
    """Parse MD file -> CardData. Raises ValueError on invalid frontmatter."""
    post = frontmatter.load(str(file_path))
    meta = post.metadata
    errors = validate_frontmatter(meta)
    if errors:
        raise ValueError(f"Invalid frontmatter in {file_path}: {errors}")

    def parse_dt(val):
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(str(val))

    return CardData(
        id=meta["id"],
        list_id=meta["list_id"],
        title=meta["title"],
        description=meta.get("description"),
        content=post.content,
        status=meta["status"],
        tags=meta.get("tags", []),
        is_archived=meta.get("is_archived", False),
        created_at=parse_dt(meta.get("created_at", datetime.now(timezone.utc))),
        updated_at=parse_dt(meta.get("updated_at", datetime.now(timezone.utc))),
    )


def validate_frontmatter(data: dict) -> list[str]:
    """Validate required frontmatter fields. Returns list of error messages."""
    errors = []
    if "id" not in data or not isinstance(data["id"], int):
        errors.append("missing or invalid 'id' (must be int)")
    if "list_id" not in data or not isinstance(data["list_id"], int):
        errors.append("missing or invalid 'list_id' (must be int)")
    if "title" not in data or not isinstance(data["title"], str):
        errors.append("missing or invalid 'title' (must be str)")
    if data.get("status") not in VALID_STATUSES:
        errors.append(f"invalid 'status': {data.get('status')}")
    return errors
