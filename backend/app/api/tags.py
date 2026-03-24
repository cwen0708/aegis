"""Tag CRUD + Card-Tag 操作 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from pathlib import Path

from app.database import get_session
from app.models.core import Tag, Card, CardTagLink, CardIndex
from app.core.card_file import read_card, write_card, card_file_path
from app.core.card_index import sync_card_to_index
from app.api.deps import get_card_lock

router = APIRouter(tags=["Tags"])


# ==========================================
# Schemas
# ==========================================
class TagCreateRequest(BaseModel):
    name: str
    color: Optional[str] = "gray"


class TagResponse(BaseModel):
    id: int
    name: str
    color: str


class CardTagRequest(BaseModel):
    tag_name: str


# ==========================================
# Tag CRUD
# ==========================================
@router.get("/tags/", response_model=List[TagResponse])
def list_tags(session: Session = Depends(get_session)):
    return session.exec(select(Tag).order_by(Tag.name)).all()


@router.post("/tags/", response_model=TagResponse)
def create_tag(req: TagCreateRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(Tag).where(Tag.name == req.name)).first()
    if existing:
        raise HTTPException(400, f"Tag '{req.name}' already exists")
    tag = Tag(name=req.name, color=req.color or "gray")
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int, session: Session = Depends(get_session)):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    # 清理關聯
    links = session.exec(select(CardTagLink).where(CardTagLink.tag_id == tag_id)).all()
    for link in links:
        session.delete(link)
    session.delete(tag)
    session.commit()
    return {"ok": True}


# ==========================================
# Card-Tag 操作
# ==========================================
def _get_or_create_tag(session: Session, name: str) -> Tag:
    """取得 Tag，不存在則自動建立。"""
    tag = session.exec(select(Tag).where(Tag.name == name)).first()
    if not tag:
        tag = Tag(name=name, color="gray")
        session.add(tag)
        session.commit()
        session.refresh(tag)
    return tag


def _get_card_index_and_project(session: Session, card_id: int):
    """取得 CardIndex 和 project_path，找不到則 raise 404。"""
    idx = session.get(CardIndex, card_id)
    if not idx:
        raise HTTPException(404, f"Card #{card_id} not found")
    from app.models.core import Project
    project = session.get(Project, idx.project_id)
    if not project or not project.path:
        raise HTTPException(404, f"Project for card #{card_id} not found")
    return idx, project


@router.get("/cards/{card_id}/tags", response_model=List[str])
def get_card_tags(card_id: int, session: Session = Depends(get_session)):
    idx, _ = _get_card_index_and_project(session, card_id)
    import json
    return json.loads(idx.tags_json) if idx.tags_json else []


@router.post("/cards/{card_id}/tags")
async def add_card_tag(card_id: int, req: CardTagRequest, session: Session = Depends(get_session)):
    """為卡片加上 tag（不存在則自動建立 Tag）。"""
    import json

    lock = get_card_lock(card_id)
    async with lock:
        idx, project = _get_card_index_and_project(session, card_id)
        tag = _get_or_create_tag(session, req.tag_name)

        # 1) 更新 MD 檔
        fpath = card_file_path(project.path, card_id)
        if fpath.exists():
            card_data = read_card(fpath)
            if req.tag_name not in card_data.tags:
                card_data.tags.append(req.tag_name)
                write_card(fpath, card_data)
                sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))
        else:
            # MD 不存在，只更新 CardIndex
            tags = json.loads(idx.tags_json) if idx.tags_json else []
            if req.tag_name not in tags:
                tags.append(req.tag_name)
                idx.tags_json = json.dumps(tags, ensure_ascii=False)
                session.add(idx)

        # 2) Dual-write: ORM CardTagLink
        orm_card = session.get(Card, card_id)
        if orm_card:
            existing_link = session.exec(
                select(CardTagLink).where(
                    CardTagLink.card_id == card_id,
                    CardTagLink.tag_id == tag.id,
                )
            ).first()
            if not existing_link:
                session.add(CardTagLink(card_id=card_id, tag_id=tag.id))

        session.commit()

    return {"ok": True, "card_id": card_id, "tag": req.tag_name}


@router.delete("/cards/{card_id}/tags/{tag_name}")
async def remove_card_tag(card_id: int, tag_name: str, session: Session = Depends(get_session)):
    """移除卡片的 tag。"""
    import json

    lock = get_card_lock(card_id)
    async with lock:
        idx, project = _get_card_index_and_project(session, card_id)

        # 1) 更新 MD 檔
        fpath = card_file_path(project.path, card_id)
        if fpath.exists():
            card_data = read_card(fpath)
            if tag_name in card_data.tags:
                card_data.tags.remove(tag_name)
                write_card(fpath, card_data)
                sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))
        else:
            tags = json.loads(idx.tags_json) if idx.tags_json else []
            if tag_name in tags:
                tags.remove(tag_name)
                idx.tags_json = json.dumps(tags, ensure_ascii=False)
                session.add(idx)

        # 2) Dual-write: 移除 ORM CardTagLink
        tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
        if tag:
            link = session.exec(
                select(CardTagLink).where(
                    CardTagLink.card_id == card_id,
                    CardTagLink.tag_id == tag.id,
                )
            ).first()
            if link:
                session.delete(link)

        session.commit()

    return {"ok": True, "card_id": card_id, "removed": tag_name}
