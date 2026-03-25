"""usage-dashboard 端點測試：空資料、多筆資料、日期範圍、分組"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Member, TaskLog
from app.api.members import usage_dashboard


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session: Session, records: list[dict]):
    for r in records:
        session.add(TaskLog(**r))
    session.commit()


def _seed_member(session: Session, **kwargs) -> int:
    m = Member(**kwargs)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m.id


# ---- 空資料 ----
def test_empty_data(db_session):
    result = usage_dashboard(session=db_session)
    assert result["group_by"] == "date"
    assert result["days"] == 30
    assert result["items"] == []


# ---- 多筆資料 + group_by=date ----
def test_group_by_date(db_session):
    now = datetime.now(timezone.utc)
    _seed(db_session, [
        {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01, "provider": "claude", "created_at": now - timedelta(days=1)},
        {"input_tokens": 200, "output_tokens": 80, "cost_usd": 0.02, "provider": "claude", "created_at": now - timedelta(days=1)},
        {"input_tokens": 300, "output_tokens": 120, "cost_usd": 0.05, "provider": "gemini", "created_at": now},
    ])
    result = usage_dashboard(days=7, group_by="date", session=db_session)
    items = result["items"]
    assert len(items) == 2
    # 第一天合計
    day1 = items[0]
    assert day1["input_tokens"] == 300
    assert day1["output_tokens"] == 130
    assert abs(day1["cost_usd"] - 0.03) < 1e-9
    assert day1["tasks"] == 2


# ---- group_by=member（含成員名稱 + cost 降序）----
def test_group_by_member(db_session):
    now = datetime.now(timezone.utc)
    m1 = _seed_member(db_session, name="小茵", slug="xiao-yin")
    m2 = _seed_member(db_session, name="小良", slug="xiao-liang")
    _seed(db_session, [
        {"member_id": m1, "cost_usd": 0.01, "provider": "claude", "created_at": now},
        {"member_id": m2, "cost_usd": 0.10, "provider": "claude", "created_at": now},
        {"member_id": m2, "cost_usd": 0.05, "provider": "gemini", "created_at": now},
    ])
    result = usage_dashboard(group_by="member", session=db_session)
    items = result["items"]
    assert len(items) == 2
    # cost 降序：小良排第一
    assert items[0]["member_name"] == "小良"
    assert abs(items[0]["cost_usd"] - 0.15) < 1e-9
    assert items[1]["member_name"] == "小茵"


# ---- group_by=provider ----
def test_group_by_provider(db_session):
    now = datetime.now(timezone.utc)
    _seed(db_session, [
        {"provider": "claude", "cost_usd": 0.03, "created_at": now},
        {"provider": "claude", "cost_usd": 0.02, "created_at": now},
        {"provider": "gemini", "cost_usd": 0.01, "created_at": now},
    ])
    result = usage_dashboard(group_by="provider", session=db_session)
    items = result["items"]
    providers = {i["provider"] for i in items}
    assert providers == {"claude", "gemini"}


# ---- 日期範圍過濾：超出範圍的不應出現 ----
def test_date_range_filter(db_session):
    now = datetime.now(timezone.utc)
    _seed(db_session, [
        {"cost_usd": 0.01, "provider": "claude", "created_at": now - timedelta(days=60)},
        {"cost_usd": 0.02, "provider": "claude", "created_at": now},
    ])
    result = usage_dashboard(days=7, session=db_session)
    items = result["items"]
    assert len(items) == 1
    assert abs(items[0]["cost_usd"] - 0.02) < 1e-9


# ---- 無效 group_by ----
def test_invalid_group_by(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        usage_dashboard(group_by="invalid", session=db_session)
    assert exc_info.value.status_code == 400
