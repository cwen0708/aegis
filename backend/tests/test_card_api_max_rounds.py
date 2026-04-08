"""Card API max_rounds 欄位測試 — 建卡、更新、驗證範圍"""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Project, Card, StageList, CardIndex
from app.core.card_file import CardData, write_card, read_card, card_file_path
from app.core.card_index import sync_card_to_index


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_project(db_session, tmp_path):
    project_path = tmp_path / "test-project"
    cards_dir = project_path / ".aegis" / "cards"
    cards_dir.mkdir(parents=True)

    project = Project(id=1, name="Test Project", path=str(project_path))
    db_session.add(project)

    backlog = StageList(id=1, project_id=1, name="Backlog", position=0, is_ai_stage=False)
    db_session.add(backlog)
    db_session.commit()

    return {"project": project, "backlog": backlog, "project_path": project_path}


# ========== 建卡時帶 max_rounds ==========

class TestCardCreateMaxRounds:
    """建卡時透過 CardData 設定 max_rounds，驗證 MD 寫入與 index 同步。"""

    def test_create_with_max_rounds(self, db_session, setup_project):
        """建卡帶 max_rounds=3，CardData 與 MD frontmatter 應正確保存。"""
        project_path = setup_project["project_path"]
        now = datetime.now(timezone.utc)

        card_data = CardData(
            id=1, list_id=1, title="Loop Task",
            description="多輪任務", content="執行三輪迭代",
            status="idle", tags=[], max_rounds=3,
            created_at=now, updated_at=now,
        )

        fpath = card_file_path(str(project_path), 1)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        write_card(fpath, card_data)

        # 驗證讀回 max_rounds 正確
        loaded = read_card(fpath)
        assert loaded.max_rounds == 3

        # 驗證 index 同步
        sync_card_to_index(db_session, card_data, project_id=1, file_path=str(fpath))
        db_session.commit()

        idx = db_session.get(CardIndex, 1)
        assert idx is not None
        assert idx.max_rounds == 3

    def test_create_without_max_rounds_defaults_to_1(self, db_session, setup_project):
        """不帶 max_rounds 時，預設為 1（不觸發 loop）。"""
        project_path = setup_project["project_path"]
        now = datetime.now(timezone.utc)

        card_data = CardData(
            id=2, list_id=1, title="Single Task",
            description=None, content="單輪任務",
            status="idle", tags=[],
            created_at=now, updated_at=now,
        )

        fpath = card_file_path(str(project_path), 2)
        write_card(fpath, card_data)

        loaded = read_card(fpath)
        assert loaded.max_rounds == 1

        sync_card_to_index(db_session, card_data, project_id=1, file_path=str(fpath))
        db_session.commit()

        idx = db_session.get(CardIndex, 2)
        assert idx.max_rounds == 1


# ========== 更新 max_rounds ==========

class TestCardUpdateMaxRounds:
    """更新卡片的 max_rounds，驗證 MD frontmatter 與 index 同步更新。"""

    def test_update_max_rounds(self, db_session, setup_project):
        """建卡後將 max_rounds 從 1 更新為 5，驗證寫入。"""
        project_path = setup_project["project_path"]
        now = datetime.now(timezone.utc)

        card_data = CardData(
            id=3, list_id=1, title="Updatable Task",
            description=None, content="內容",
            status="idle", tags=[],
            created_at=now, updated_at=now,
        )

        fpath = card_file_path(str(project_path), 3)
        write_card(fpath, card_data)

        # 更新 max_rounds
        cd = read_card(fpath)
        assert cd.max_rounds == 1

        cd.max_rounds = 5
        cd.updated_at = datetime.now(timezone.utc)
        write_card(fpath, cd)

        # 驗證 MD 更新
        reloaded = read_card(fpath)
        assert reloaded.max_rounds == 5

        # 驗證 index 同步
        sync_card_to_index(db_session, cd, project_id=1, file_path=str(fpath))
        db_session.commit()

        idx = db_session.get(CardIndex, 3)
        assert idx.max_rounds == 5

    def test_max_rounds_1_not_in_frontmatter(self, db_session, setup_project):
        """max_rounds=1 時不寫入 frontmatter（保持向後相容）。"""
        project_path = setup_project["project_path"]
        now = datetime.now(timezone.utc)

        card_data = CardData(
            id=4, list_id=1, title="Default Task",
            description=None, content="內容",
            status="idle", tags=[],
            created_at=now, updated_at=now,
        )

        fpath = card_file_path(str(project_path), 4)
        write_card(fpath, card_data)

        raw = fpath.read_text(encoding="utf-8")
        assert "max_rounds" not in raw


# ========== Request Model 驗證 ==========

class TestMaxRoundsValidation:
    """CardCreateRequest / CardUpdateRequest 的 max_rounds 驗證（1~10）。"""

    def test_valid_range(self):
        from app.api.cards import CardCreateRequest
        req = CardCreateRequest(list_id=1, title="Test", max_rounds=5)
        assert req.max_rounds == 5

    def test_min_boundary(self):
        from app.api.cards import CardCreateRequest
        req = CardCreateRequest(list_id=1, title="Test", max_rounds=1)
        assert req.max_rounds == 1

    def test_max_boundary(self):
        from app.api.cards import CardCreateRequest
        req = CardCreateRequest(list_id=1, title="Test", max_rounds=10)
        assert req.max_rounds == 10

    def test_zero_rejected(self):
        from app.api.cards import CardCreateRequest
        with pytest.raises(Exception):
            CardCreateRequest(list_id=1, title="Test", max_rounds=0)

    def test_negative_rejected(self):
        from app.api.cards import CardCreateRequest
        with pytest.raises(Exception):
            CardCreateRequest(list_id=1, title="Test", max_rounds=-1)

    def test_over_10_rejected(self):
        from app.api.cards import CardCreateRequest
        with pytest.raises(Exception):
            CardCreateRequest(list_id=1, title="Test", max_rounds=11)

    def test_none_accepted(self):
        from app.api.cards import CardCreateRequest
        req = CardCreateRequest(list_id=1, title="Test", max_rounds=None)
        assert req.max_rounds is None

    def test_omitted_defaults_to_none(self):
        from app.api.cards import CardCreateRequest
        req = CardCreateRequest(list_id=1, title="Test")
        assert req.max_rounds is None

    def test_update_request_validation(self):
        from app.api.cards import CardUpdateRequest
        with pytest.raises(Exception):
            CardUpdateRequest(max_rounds=0)

    def test_update_request_valid(self):
        from app.api.cards import CardUpdateRequest
        req = CardUpdateRequest(max_rounds=7)
        assert req.max_rounds == 7
