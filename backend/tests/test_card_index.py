import json
from datetime import datetime, timezone
from sqlmodel import Session, select
from app.models.core import CardIndex
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import (
    sync_card_to_index,
    remove_card_from_index,
    query_pending_cards,
    query_board,
    query_archived,
    rebuild_index,
    next_card_id,
)


def _make_card(id, list_id=1, status="idle", title="Test", tags=None):
    return CardData(
        id=id, list_id=list_id, title=title, description="desc",
        content="body", status=status, tags=tags or [],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_sync_and_query(db_session, tmp_project):
    card = _make_card(1, status="pending", tags=["Bug"])
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    results = query_pending_cards(db_session)
    assert len(results) == 1
    assert results[0].card_id == 1
    assert results[0].status == "pending"
    assert json.loads(results[0].tags_json) == ["Bug"]


def test_sync_upsert(db_session, tmp_project):
    """Second sync updates existing entry."""
    card = _make_card(1, status="idle")
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    card.status = "pending"
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    idx = db_session.get(CardIndex, 1)
    assert idx.status == "pending"


def test_remove_from_index(db_session, tmp_project):
    card = _make_card(1)
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    remove_card_from_index(db_session, card_id=1)
    db_session.commit()
    assert db_session.get(CardIndex, 1) is None


def test_query_board(db_session, tmp_project):
    for i in range(3):
        card = _make_card(i + 1, list_id=10, title=f"Card {i}")
        fpath = card_file_path(str(tmp_project), i + 1)
        write_card(fpath, card)
        sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    results = query_board(db_session, project_id=1)
    assert len(results) == 3


def test_query_board_filters_project(db_session, tmp_project):
    card1 = _make_card(1)
    card2 = _make_card(2)
    fpath1 = card_file_path(str(tmp_project), 1)
    fpath2 = card_file_path(str(tmp_project), 2)
    write_card(fpath1, card1)
    write_card(fpath2, card2)
    sync_card_to_index(db_session, card1, project_id=1, file_path=str(fpath1))
    sync_card_to_index(db_session, card2, project_id=99, file_path=str(fpath2))
    db_session.commit()

    assert len(query_board(db_session, project_id=1)) == 1
    assert len(query_board(db_session, project_id=99)) == 1


def test_rebuild_index(db_session, tmp_project):
    for i in range(3):
        card = _make_card(i + 1, list_id=5)
        write_card(card_file_path(str(tmp_project), i + 1), card)

    count = rebuild_index(db_session, project_id=1, project_path=str(tmp_project))
    db_session.commit()
    assert count == 3
    assert db_session.get(CardIndex, 1) is not None
    assert db_session.get(CardIndex, 3) is not None


def test_rebuild_index_empty_dir(db_session, tmp_path):
    count = rebuild_index(db_session, project_id=1, project_path=str(tmp_path))
    assert count == 0


def test_next_card_id_empty(db_session):
    assert next_card_id(db_session) == 1


def test_query_archived(db_session, tmp_project):
    """query_archived 應回傳已歸檔的卡片"""
    # 建立一張已歸檔、一張未歸檔的卡片
    card_active = _make_card(1)
    card_archived = _make_card(2)
    card_archived.is_archived = True

    fpath1 = card_file_path(str(tmp_project), 1)
    fpath2 = card_file_path(str(tmp_project), 2)
    write_card(fpath1, card_active)
    write_card(fpath2, card_archived)
    sync_card_to_index(db_session, card_active, project_id=1, file_path=str(fpath1))
    sync_card_to_index(db_session, card_archived, project_id=1, file_path=str(fpath2))
    db_session.commit()

    results = query_archived(db_session, project_id=1)
    assert len(results) == 1
    assert results[0].card_id == 2
    assert results[0].is_archived is True

    # query_board 不應包含已歸檔卡片
    board = query_board(db_session, project_id=1)
    assert len(board) == 1
    assert board[0].card_id == 1


def test_next_card_id_increments(db_session, tmp_project):
    card = _make_card(42)
    fpath = card_file_path(str(tmp_project), 42)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()
    assert next_card_id(db_session) == 43
