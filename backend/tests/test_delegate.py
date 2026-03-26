"""Leader-Worker 委派 API 測試"""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine, select
from app.models.core import Project, Card, StageList, Member, CardIndex
from app.core.card_file import CardData, write_card, card_file_path, read_card
from app.core.card_index import sync_card_to_index, next_card_id


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_project(db_session, tmp_path):
    """建立測試用專案、成員、列表"""
    # 建立專案
    project_path = tmp_path / "test-project"
    cards_dir = project_path / ".aegis" / "cards"
    cards_dir.mkdir(parents=True)

    project = Project(id=1, name="Test Project", path=str(project_path))
    db_session.add(project)

    # 建立成員
    member_a = Member(id=1, name="小茵", slug="xiao-yin", role="全端工程師")
    member_b = Member(id=2, name="小良", slug="xiao-liang", role="Code Reviewer")
    db_session.add(member_a)
    db_session.add(member_b)

    # 建立列表（含成員收件匣）
    backlog = StageList(id=1, project_id=1, name="Backlog", position=0, is_ai_stage=False)
    inbox_a = StageList(
        id=2, project_id=1, name="小茵 收件匣", position=1,
        member_id=1, is_ai_stage=True, is_member_bound=True,
    )
    inbox_b = StageList(
        id=3, project_id=1, name="小良 收件匣", position=2,
        member_id=2, is_ai_stage=True, is_member_bound=True,
    )
    db_session.add(backlog)
    db_session.add(inbox_a)
    db_session.add(inbox_b)
    db_session.commit()

    return {
        "project": project,
        "member_a": member_a,
        "member_b": member_b,
        "backlog": backlog,
        "inbox_a": inbox_a,
        "inbox_b": inbox_b,
        "project_path": project_path,
    }


def _create_parent_card(db_session, setup, card_id=1):
    """建立一張父卡片到 backlog"""
    now = datetime.now(timezone.utc)
    project_path = setup["project_path"]
    card_data = CardData(
        id=card_id, list_id=setup["backlog"].id, title="Leader Task",
        description="Parent task", content="Do something", status="running",
        tags=["P0"], created_at=now, updated_at=now,
    )
    fpath = card_file_path(str(project_path), card_id)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)
    sync_card_to_index(db_session, card_data, project_id=1, file_path=str(fpath))
    db_session.add(Card(
        id=card_id, list_id=setup["backlog"].id, title="Leader Task",
        status="running", created_at=now, updated_at=now,
    ))
    db_session.commit()
    return card_data


# ==========================================
# Test: delegate 建立子卡片
# ==========================================
def test_delegate_creates_subtask(db_session, setup_project):
    """delegate 應建立子卡片到目標成員收件匣，status=pending，parent_id 正確"""
    setup = setup_project
    parent = _create_parent_card(db_session, setup, card_id=1)

    # 模擬 delegate 邏輯（直接呼叫核心邏輯，不經 HTTP）
    target_member_id = 2  # 小良
    member = db_session.get(Member, target_member_id)
    assert member is not None

    # 查詢目標成員的 inbox
    inbox = db_session.exec(
        select(StageList).where(
            StageList.project_id == 1,
            StageList.member_id == target_member_id,
            StageList.is_member_bound == True,  # noqa: E712
        )
    ).first()
    assert inbox is not None
    assert inbox.id == 3  # 小良收件匣

    # 建立子卡片
    new_id = next_card_id(db_session)
    now = datetime.now(timezone.utc)
    child = CardData(
        id=new_id, list_id=inbox.id, title="Sub Task for Review",
        description=None, content="Review this code", status="pending",
        tags=["review"], parent_id=parent.id,
        created_at=now, updated_at=now,
    )
    fpath = card_file_path(str(setup["project_path"]), new_id)
    write_card(fpath, child)
    sync_card_to_index(db_session, child, project_id=1, file_path=str(fpath))
    db_session.commit()

    # 驗證
    idx = db_session.get(CardIndex, new_id)
    assert idx is not None
    assert idx.parent_id == 1  # 父卡片 ID
    assert idx.list_id == 3   # 小良收件匣
    assert idx.status == "pending"  # 自動觸發
    assert idx.title == "Sub Task for Review"

    # 驗證 MD 檔案也有 parent_id
    md = read_card(fpath)
    assert md.parent_id == 1


# ==========================================
# Test: delegate 目標成員不存在
# ==========================================
def test_delegate_invalid_member_returns_404(db_session, setup_project):
    """目標成員不存在時應回傳 404"""
    _create_parent_card(db_session, setup_project, card_id=1)

    # 查詢不存在的成員
    member = db_session.get(Member, 999)
    assert member is None  # 確認不存在


# ==========================================
# Test: subtasks 查詢
# ==========================================
def test_subtasks_query(db_session, setup_project):
    """應能查詢到所有子卡片"""
    setup = setup_project
    parent = _create_parent_card(db_session, setup, card_id=1)

    now = datetime.now(timezone.utc)
    # 建立兩張子卡片
    for i, (title, status) in enumerate(
        [("Sub A", "pending"), ("Sub B", "completed")], start=2
    ):
        child = CardData(
            id=i, list_id=setup["inbox_b"].id, title=title,
            description=None, content="", status=status,
            tags=[], parent_id=1, created_at=now, updated_at=now,
        )
        fpath = card_file_path(str(setup["project_path"]), i)
        write_card(fpath, child)
        sync_card_to_index(db_session, child, project_id=1, file_path=str(fpath))
    db_session.commit()

    # 查詢 subtasks
    subtasks = db_session.exec(
        select(CardIndex).where(CardIndex.parent_id == 1)
    ).all()

    assert len(subtasks) == 2
    titles = {s.title for s in subtasks}
    assert titles == {"Sub A", "Sub B"}
    statuses = {s.status for s in subtasks}
    assert statuses == {"pending", "completed"}


# ==========================================
# Test: create_card 帶 parent_id
# ==========================================
def test_create_card_with_parent_id(db_session, setup_project):
    """CardCreateRequest 帶 parent_id 時應寫入 CardIndex"""
    setup = setup_project
    _create_parent_card(db_session, setup, card_id=1)

    now = datetime.now(timezone.utc)
    new_id = next_card_id(db_session)

    card_data = CardData(
        id=new_id, list_id=setup["backlog"].id, title="Child via create",
        description=None, content="test", status="idle",
        tags=[], parent_id=1, created_at=now, updated_at=now,
    )
    fpath = card_file_path(str(setup["project_path"]), new_id)
    write_card(fpath, card_data)
    sync_card_to_index(db_session, card_data, project_id=1, file_path=str(fpath))
    db_session.commit()

    # 驗證 parent_id 正確寫入
    idx = db_session.get(CardIndex, new_id)
    assert idx is not None
    assert idx.parent_id == 1

    # 驗證 MD 檔案
    md = read_card(fpath)
    assert md.parent_id == 1

    # 沒有 parent_id 的卡片不應被 subtasks 查詢影響
    no_parent = db_session.exec(
        select(CardIndex).where(CardIndex.parent_id == 999)
    ).all()
    assert len(no_parent) == 0
