"""GET/PATCH /api/v1/cards/{id} 的 max_rounds 欄位回傳驗證（#13062）。

補強 CardResponse 漏掉 max_rounds 的問題：前端需要讀現值才能做編輯 UI。
直接呼叫 endpoint function，不經 TestClient。
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Project, StageList
from app.api.cards import (
    CardCreateRequest,
    CardUpdateRequest,
    create_card,
    read_card_endpoint,
    update_card,
)


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def project_and_list(db_session, tmp_path):
    """建立最小可用的 Project + StageList，並確保 .aegis/cards/ 目錄存在。"""
    project_path = tmp_path / "proj"
    (project_path / ".aegis" / "cards").mkdir(parents=True)

    project = Project(id=1, name="P", path=str(project_path))
    db_session.add(project)
    stage = StageList(id=1, project_id=1, name="Backlog", position=0, is_ai_stage=False)
    db_session.add(stage)
    db_session.commit()
    return project, stage


class TestGetCardMaxRounds:
    """GET /cards/{id} 應回傳 max_rounds 欄位。"""

    def test_get_card_with_max_rounds_3(self, db_session, project_and_list):
        """建立 max_rounds=3 的卡片，GET 應回傳 max_rounds=3。"""
        create_card(
            CardCreateRequest(list_id=1, title="Loop 3 rounds", max_rounds=3),
            session=db_session,
        )

        resp = read_card_endpoint(card_id=1, session=db_session)
        assert resp.max_rounds == 3

    def test_get_card_default_max_rounds_1(self, db_session, project_and_list):
        """未指定 max_rounds 時，GET 應回傳預設值 1。"""
        create_card(
            CardCreateRequest(list_id=1, title="Single round"),
            session=db_session,
        )

        resp = read_card_endpoint(card_id=1, session=db_session)
        assert resp.max_rounds == 1

    def test_get_card_after_patch_max_rounds(self, db_session, project_and_list):
        """PATCH max_rounds=5 後，GET 應回傳 max_rounds=5。"""
        create_card(
            CardCreateRequest(list_id=1, title="Patchable", max_rounds=2),
            session=db_session,
        )

        update_card(
            card_id=1,
            update_data=CardUpdateRequest(max_rounds=5),
            actor="human",
            session=db_session,
        )

        resp = read_card_endpoint(card_id=1, session=db_session)
        assert resp.max_rounds == 5
