"""File watcher for external MD card changes."""
import asyncio
import logging
import re
from pathlib import Path

from watchfiles import awatch, Change
from sqlmodel import Session, select

from app.database import engine
from app.models.core import CardIndex, Project
from app.core.card_file import read_card, consume_internal_write
from app.core.card_index import sync_card_to_index, remove_card_from_index

logger = logging.getLogger(__name__)

# Pattern to extract card ID from filename like card-000042.md
CARD_FILENAME_RE = re.compile(r"card-(\d+)\.md$")

_watcher_task: asyncio.Task | None = None


def _parse_card_id_from_filename(filename: str) -> int | None:
    """Extract card ID from filename like card-000042.md."""
    m = CARD_FILENAME_RE.search(filename)
    return int(m.group(1)) if m else None


async def _handle_change(change_type: Change, path_str: str):
    """Handle a single file change event."""
    path = Path(path_str)

    # Only care about card MD files
    card_id = _parse_card_id_from_filename(path.name)
    if card_id is None:
        return

    # 內部寫入（write_card）已標記，跳過避免競態條件
    if change_type != Change.deleted and consume_internal_write(path):
        return

    if change_type == Change.deleted:
        # File was deleted externally — remove from index
        with Session(engine) as session:
            remove_card_from_index(session, card_id)
            session.commit()
        logger.info(f"Card {card_id} deleted externally, removed from index")
        try:
            from app.core.ws_manager import broadcast_event
            await broadcast_event("card_deleted", {"card_id": card_id})
        except Exception:
            pass
        return

    # For added/modified: check mtime against index
    if not path.exists():
        return

    current_mtime = path.stat().st_mtime

    with Session(engine) as session:
        idx = session.get(CardIndex, card_id)
        if idx and abs(idx.file_mtime - current_mtime) < 0.01:
            return  # Internal write — mtime already synced, skip

        # External modification — parse and update index
        try:
            card = read_card(path)

            # Determine project_id from existing index or directory structure
            project_id = idx.project_id if idx else 0
            if project_id == 0:
                # Try to find project by matching path
                projects = session.exec(select(Project)).all()
                for p in projects:
                    if str(path).startswith(p.path):
                        project_id = p.id
                        break

            sync_card_to_index(session, card, project_id, str(path))
            session.commit()
            logger.info(f"Card {card_id} updated from external edit")

            try:
                from app.core.ws_manager import broadcast_event
                await broadcast_event("card_updated", {"card_id": card_id})
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Failed to parse externally modified {path}: {e}")


async def _watch_directories(paths: list[str]):
    """Watch multiple directories for changes."""
    watch_paths = []
    for p in paths:
        cards_dir = Path(p) / ".aegis" / "cards"
        if cards_dir.exists():
            watch_paths.append(str(cards_dir))

    if not watch_paths:
        logger.info("No card directories to watch")
        return

    logger.info(f"Watching {len(watch_paths)} card directories for changes")

    try:
        async for changes in awatch(*watch_paths):
            for change_type, change_path in changes:
                try:
                    await _handle_change(change_type, change_path)
                except Exception as e:
                    logger.error(f"Error handling file change {change_path}: {e}")
    except asyncio.CancelledError:
        logger.info("Card watcher cancelled")
    except Exception as e:
        logger.error(f"Card watcher error: {e}")


async def start_card_watcher():
    """Start watching all active project card directories."""
    global _watcher_task

    # Get all active project paths
    with Session(engine) as session:
        projects = session.exec(
            select(Project).where(Project.is_active == True)  # noqa: E712
        ).all()
        paths = [p.path for p in projects if p.path]

    if not paths:
        logger.info("No active projects, card watcher not started")
        return

    _watcher_task = asyncio.create_task(_watch_directories(paths))
    logger.info("Card watcher started")


async def stop_card_watcher():
    """Stop the file watcher."""
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
        try:
            await _watcher_task
        except asyncio.CancelledError:
            pass
    _watcher_task = None
    logger.info("Card watcher stopped")
