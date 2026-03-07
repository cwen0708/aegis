"""Tests for card_watcher module."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from pathlib import Path

from watchfiles import Change
from sqlmodel import Session

from app.models.core import CardIndex
from app.core.card_file import CardData, write_card, card_file_path, _internal_writes
from app.core.card_index import sync_card_to_index
from app.core.card_watcher import _parse_card_id_from_filename, _handle_change


# ---- _parse_card_id_from_filename ----

def test_parse_card_id_normal():
    assert _parse_card_id_from_filename("card-000042.md") == 42


def test_parse_card_id_small():
    assert _parse_card_id_from_filename("card-000001.md") == 1


def test_parse_card_id_large():
    assert _parse_card_id_from_filename("card-999999.md") == 999999


def test_parse_card_id_returns_none_for_non_card():
    assert _parse_card_id_from_filename("readme.md") is None
    assert _parse_card_id_from_filename("card-.md") is None
    assert _parse_card_id_from_filename("notes.txt") is None
    assert _parse_card_id_from_filename("card-abc.md") is None


def test_parse_card_id_from_full_path():
    assert _parse_card_id_from_filename("/some/path/.aegis/cards/card-000007.md") == 7


# ---- _handle_change (with real DB) ----

def _make_card(card_id, **kwargs):
    defaults = dict(
        id=card_id, list_id=1, title="Test Card", description="desc",
        content="body", status="idle", tags=[],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return CardData(**defaults)


@pytest.mark.asyncio
async def test_handle_change_modified_updates_index(db_session, tmp_project):
    """External modification re-parses the file and updates the index."""
    card = _make_card(5, title="Original")
    fpath = card_file_path(str(tmp_project), 5)
    write_card(fpath, card)

    # Sync to index with a stale mtime (simulate internal write was long ago)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    idx = db_session.get(CardIndex, 5)
    idx.file_mtime = 0.0  # Force mtime mismatch so watcher treats it as external
    db_session.add(idx)
    db_session.commit()

    # Now externally modify the file
    card.title = "Externally Modified"
    write_card(fpath, card)
    _internal_writes.clear()  # 模擬外部編輯：清除 suppression 標記

    # Patch engine so _handle_change uses our test DB
    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        with patch("app.core.ws_manager.broadcast_event", new_callable=AsyncMock):
            await _handle_change(Change.modified, str(fpath))

    # Refresh session to see changes
    db_session.expire_all()
    updated = db_session.get(CardIndex, 5)
    assert updated is not None
    assert updated.title == "Externally Modified"


@pytest.mark.asyncio
async def test_handle_change_deleted_removes_index(db_session, tmp_project):
    """Deleted file removes the card from the index."""
    card = _make_card(10)
    fpath = card_file_path(str(tmp_project), 10)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    # Delete the file
    fpath.unlink()

    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        with patch("app.core.ws_manager.broadcast_event", new_callable=AsyncMock):
            await _handle_change(Change.deleted, str(fpath))

    db_session.expire_all()
    assert db_session.get(CardIndex, 10) is None


@pytest.mark.asyncio
async def test_handle_change_skips_non_card_files(db_session):
    """Non-card files are ignored."""
    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        # Should return without error
        await _handle_change(Change.modified, "/some/path/readme.md")


@pytest.mark.asyncio
async def test_handle_change_skips_internal_write(db_session, tmp_project):
    """When mtime matches the index, the change is skipped (internal write)."""
    card = _make_card(20)
    fpath = card_file_path(str(tmp_project), 20)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    # mtime in index should match file — this should be a no-op
    # 先清除 suppression set（write_card 會自動加入）
    _internal_writes.clear()
    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        with patch("app.core.card_index.sync_card_to_index") as mock_sync:
            await _handle_change(Change.modified, str(fpath))
            mock_sync.assert_not_called()


@pytest.mark.asyncio
async def test_handle_change_suppressed_by_internal_write(db_session, tmp_project):
    """write_card 標記內部寫入後，watcher 應跳過（即使 index 尚未同步）。"""
    card = _make_card(30)
    fpath = card_file_path(str(tmp_project), 30)
    write_card(fpath, card)  # 會自動標記 _internal_writes
    # 故意不呼叫 sync_card_to_index — 模擬競態條件窗口

    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        with patch("app.core.card_index.sync_card_to_index") as mock_sync:
            await _handle_change(Change.modified, str(fpath))
            mock_sync.assert_not_called()  # 應被 suppression set 攔截


@pytest.mark.asyncio
async def test_handle_change_detects_true_external_edit(db_session, tmp_project):
    """不經過 write_card 的外部編輯應正常偵測並同步。"""
    card = _make_card(40, title="Original")
    fpath = card_file_path(str(tmp_project), 40)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    # 清除 suppression set
    _internal_writes.clear()

    # 強制 mtime 不符，模擬外部編輯
    idx = db_session.get(CardIndex, 40)
    idx.file_mtime = 0.0
    db_session.add(idx)
    db_session.commit()

    # 直接寫入檔案（不經過 write_card → 不會標記 suppression）
    import frontmatter
    post = frontmatter.load(str(fpath))
    post["title"] = "Externally Changed"
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    with patch("app.core.card_watcher.engine", db_session.get_bind()):
        with patch("app.core.ws_manager.broadcast_event", new_callable=AsyncMock):
            await _handle_change(Change.modified, str(fpath))

    db_session.expire_all()
    updated = db_session.get(CardIndex, 40)
    assert updated is not None
    assert updated.title == "Externally Changed"
