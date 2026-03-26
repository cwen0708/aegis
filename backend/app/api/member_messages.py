from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from app.database import get_session
from app.models.core import MemberMessage

router = APIRouter(tags=["MemberMessages"])


class MemberMessageCreate(BaseModel):
    from_member_id: int
    to_member_id: Optional[int] = None
    card_id: Optional[int] = None
    message_type: str = "info"
    content: str


@router.get("/member-messages")
def list_member_messages(
    card_id: Optional[int] = None,
    from_member_id: Optional[int] = None,
    to_member_id: Optional[int] = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    stmt = select(MemberMessage)
    if card_id is not None:
        stmt = stmt.where(MemberMessage.card_id == card_id)
    if from_member_id is not None:
        stmt = stmt.where(MemberMessage.from_member_id == from_member_id)
    if to_member_id is not None:
        stmt = stmt.where(MemberMessage.to_member_id == to_member_id)
    stmt = stmt.order_by(MemberMessage.created_at.desc()).limit(limit)
    return session.exec(stmt).all()


@router.post("/member-messages")
def create_member_message(
    body: MemberMessageCreate,
    session: Session = Depends(get_session),
):
    msg = MemberMessage(
        from_member_id=body.from_member_id,
        to_member_id=body.to_member_id,
        card_id=body.card_id,
        message_type=body.message_type,
        content=body.content,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg
