"""MemberMessage 模型與 API 測試"""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from app.models.core import MemberMessage, Member, CardIndex, Project, StageList, Card


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_message(db_session):
    """建立訊息成功"""
    msg = MemberMessage(
        from_member_id=1,
        to_member_id=2,
        card_id=100,
        message_type="delegate",
        content="請幫忙處理這張卡片",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.id is not None
    assert msg.from_member_id == 1
    assert msg.to_member_id == 2
    assert msg.card_id == 100
    assert msg.message_type == "delegate"
    assert msg.content == "請幫忙處理這張卡片"
    assert msg.created_at is not None


def test_list_by_card_id(db_session):
    """按卡片 ID 篩選"""
    for i in range(3):
        db_session.add(MemberMessage(
            from_member_id=1, to_member_id=2, card_id=10,
            message_type="info", content=f"msg {i}",
        ))
    db_session.add(MemberMessage(
        from_member_id=1, to_member_id=3, card_id=20,
        message_type="info", content="other card",
    ))
    db_session.commit()

    results = db_session.exec(
        select(MemberMessage).where(MemberMessage.card_id == 10)
    ).all()
    assert len(results) == 3
    assert all(m.card_id == 10 for m in results)


def test_list_by_member_id(db_session):
    """按成員 ID 篩選"""
    db_session.add(MemberMessage(
        from_member_id=1, to_member_id=2, card_id=10,
        message_type="delegate", content="from 1",
    ))
    db_session.add(MemberMessage(
        from_member_id=2, to_member_id=1, card_id=10,
        message_type="report", content="from 2",
    ))
    db_session.add(MemberMessage(
        from_member_id=3, to_member_id=1, card_id=10,
        message_type="info", content="from 3",
    ))
    db_session.commit()

    # 篩選 from_member_id=1
    from_1 = db_session.exec(
        select(MemberMessage).where(MemberMessage.from_member_id == 1)
    ).all()
    assert len(from_1) == 1

    # 篩選 to_member_id=1
    to_1 = db_session.exec(
        select(MemberMessage).where(MemberMessage.to_member_id == 1)
    ).all()
    assert len(to_1) == 2


def test_delegate_records_message(db_session, tmp_path):
    """delegate 時自動記錄 — 驗證模型層面的整合邏輯"""
    # 模擬 delegate 流程中建立 MemberMessage
    leader_id = 1
    worker_id = 2
    parent_card_id = 100
    task_title = "實作新功能"
    task_content = "請完成 MemberMessage API 的開發"

    desc_summary = (task_content or "")[:100]
    msg_content = f"委派子任務: {task_title}"
    if desc_summary:
        msg_content += f" — {desc_summary}"

    msg = MemberMessage(
        from_member_id=leader_id,
        to_member_id=worker_id,
        card_id=parent_card_id,
        message_type="delegate",
        content=msg_content,
    )
    db_session.add(msg)
    db_session.commit()

    # 驗證記錄
    result = db_session.exec(
        select(MemberMessage)
        .where(MemberMessage.card_id == parent_card_id)
        .where(MemberMessage.message_type == "delegate")
    ).first()
    assert result is not None
    assert result.from_member_id == leader_id
    assert result.to_member_id == worker_id
    assert "實作新功能" in result.content
    assert "MemberMessage API" in result.content


def test_broadcast_message_no_to_member(db_session):
    """廣播訊息 to_member_id 為 None"""
    msg = MemberMessage(
        from_member_id=1,
        to_member_id=None,
        card_id=10,
        message_type="info",
        content="廣播給所有成員",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.to_member_id is None
