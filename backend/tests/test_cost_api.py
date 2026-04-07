"""成本查詢 API 測試 — GET /cards/{id}/cost + GET /projects/{id}/cost"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Project, CardIndex
from app.api.cards import get_card_cost
from app.api.projects import get_project_cost


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_project(session: Session, project_id: int) -> Project:
    p = Project(id=project_id, name=f"proj-{project_id}", path=f"/tmp/proj-{project_id}")
    session.add(p)
    session.commit()
    return p


def _seed_card_index(session: Session, **kwargs) -> CardIndex:
    idx = CardIndex(**kwargs)
    session.add(idx)
    session.commit()
    return idx


class TestCardCostEndpoint:
    def test_card_not_found_raises_404(self, db_session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_card_cost(card_id=9999, session=db_session)
        assert exc_info.value.status_code == 404

    def test_returns_zero_by_default(self, db_session):
        _seed_card_index(db_session, card_id=1, project_id=10, title="test card")
        result = get_card_cost(card_id=1, session=db_session)
        assert result["card_id"] == 1
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["estimated_cost_usd"] == 0.0

    def test_returns_accumulated_cost(self, db_session):
        _seed_card_index(
            db_session,
            card_id=2,
            project_id=10,
            title="card with cost",
            total_input_tokens=5000,
            total_output_tokens=1200,
            estimated_cost_usd=0.0087,
        )
        result = get_card_cost(card_id=2, session=db_session)
        assert result["total_input_tokens"] == 5000
        assert result["total_output_tokens"] == 1200
        assert abs(result["estimated_cost_usd"] - 0.0087) < 1e-6


class TestProjectCostEndpoint:
    def test_project_not_found_raises_404(self, db_session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_project_cost(project_id=9999, session=db_session)
        assert exc_info.value.status_code == 404

    def test_empty_project_returns_zeros(self, db_session):
        _seed_project(db_session, project_id=1)
        result = get_project_cost(project_id=1, session=db_session)
        assert result["project_id"] == 1
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["estimated_cost_usd"] == 0.0
        assert result["card_count"] == 0

    def test_aggregates_multiple_cards(self, db_session):
        _seed_project(db_session, project_id=2)
        _seed_card_index(
            db_session, card_id=10, project_id=2, title="card A",
            total_input_tokens=3000, total_output_tokens=800, estimated_cost_usd=0.005,
        )
        _seed_card_index(
            db_session, card_id=11, project_id=2, title="card B",
            total_input_tokens=2000, total_output_tokens=400, estimated_cost_usd=0.003,
        )
        result = get_project_cost(project_id=2, session=db_session)
        assert result["total_input_tokens"] == 5000
        assert result["total_output_tokens"] == 1200
        assert abs(result["estimated_cost_usd"] - 0.008) < 1e-6
        assert result["card_count"] == 2

    def test_excludes_archived_cards(self, db_session):
        _seed_project(db_session, project_id=3)
        _seed_card_index(
            db_session, card_id=20, project_id=3, title="active",
            total_input_tokens=1000, total_output_tokens=200, estimated_cost_usd=0.001,
        )
        _seed_card_index(
            db_session, card_id=21, project_id=3, title="archived",
            is_archived=True,
            total_input_tokens=9999, total_output_tokens=9999, estimated_cost_usd=9.999,
        )
        result = get_project_cost(project_id=3, session=db_session)
        assert result["card_count"] == 1
        assert result["total_input_tokens"] == 1000
