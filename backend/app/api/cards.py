from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from sqlalchemy import func as sa_func
from typing import List, Optional
from pydantic import BaseModel, field_validator
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import Project, Card, StageList, CardIndex
from app.core.card_file import CardData, read_card as read_card_md, write_card, card_file_path
from app.core.card_index import sync_card_to_index, remove_card_from_index, next_card_id
from app.core.paths import WORKSPACES_ROOT
from app.api.deps import get_card_lock, get_project_for_list
from pathlib import Path
import asyncio
import mimetypes

router = APIRouter(tags=["Cards"])

# Reference to the shared card locks dict from deps
from app.api.deps import _card_locks

# ==========================================
# Card Schemas
# ==========================================
class CardCreateRequest(BaseModel):
    list_id: int
    title: str
    description: Optional[str] = None
    content: Optional[str] = None  # 卡片內容（會被當作 AI prompt）
    status: Optional[str] = None  # idle (default) or pending
    tags: Optional[List[str]] = None  # 標籤名稱列表
    parent_id: Optional[int] = None  # 父卡片 ID（Leader-Worker 委派）
    max_rounds: Optional[int] = None  # Ralph Loop 最大迭代輪數（1~10）
    acceptance_criteria: Optional[str] = None  # 完成條件（Sprint Contract）

    @field_validator("max_rounds")
    @classmethod
    def validate_max_rounds(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 10):
            raise ValueError("max_rounds must be between 1 and 10")
        return v

class CardUpdateRequest(BaseModel):
    list_id: Optional[int] = None
    status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None  # 標籤名稱列表
    max_rounds: Optional[int] = None  # Ralph Loop 最大迭代輪數（1~10）
    acceptance_criteria: Optional[str] = None  # 完成條件（Sprint Contract）

    @field_validator("max_rounds")
    @classmethod
    def validate_max_rounds(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 10):
            raise ValueError("max_rounds must be between 1 and 10")
        return v


# ==========================================
# Card Routes
# ==========================================
@router.get("/cards/", response_model=List[Card])
def read_cards(session: Session = Depends(get_session)):
    cards = session.exec(select(Card)).all()
    return cards

@router.get("/cards/{card_id}", response_model=Card)
def read_card_endpoint(card_id: int, session: Session = Depends(get_session)):
    # Primary: look up CardIndex -> read MD file
    idx = session.get(CardIndex, card_id)
    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))
        # Return as Card-compatible dict (response_model=Card)
        return Card(
            id=cd.id, list_id=cd.list_id, title=cd.title,
            description=cd.description, content=cd.content,
            status=cd.status, created_at=cd.created_at, updated_at=cd.updated_at,
        )
    # Fallback: old Card table
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card

@router.post("/cards/", response_model=Card)
def create_card(card_in: CardCreateRequest, session: Session = Depends(get_session)):
    # Resolve project from list_id
    project, sl = get_project_for_list(session, card_in.list_id)

    # Get next card ID (max of both old Card table and CardIndex)
    new_id = next_card_id(session)
    # Also check old Card table max id（用 SQL 聚合避免全表掃描）
    old_max_id = session.exec(select(sa_func.max(Card.id))).one()
    if old_max_id is not None:
        new_id = max(new_id, old_max_id + 1)

    now = datetime.now(timezone.utc)
    initial_status = card_in.status if card_in.status in ("idle", "pending") else "idle"
    card_data = CardData(
        id=new_id, list_id=card_in.list_id, title=card_in.title,
        description=card_in.description, content=card_in.content or "", status=initial_status,
        tags=card_in.tags or [], parent_id=card_in.parent_id,
        max_rounds=card_in.max_rounds if card_in.max_rounds is not None else 1,
        acceptance_criteria=card_in.acceptance_criteria,
        created_at=now, updated_at=now,
    )

    # Write MD file
    fpath = card_file_path(project.path, new_id)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)

    # Sync to index
    sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

    # Dual-write: also create old Card ORM record (transition)
    orm_card = Card(
        id=new_id, list_id=card_in.list_id, title=card_in.title,
        description=card_in.description, status=initial_status,
        created_at=now, updated_at=now,
    )
    session.add(orm_card)
    session.commit()
    session.refresh(orm_card)
    return orm_card

@router.patch("/cards/{card_id}", response_model=Card)
def update_card(card_id: int, update_data: CardUpdateRequest, session: Session = Depends(get_session)):
    # Try MD-driven path first
    idx = session.get(CardIndex, card_id)
    now = datetime.now(timezone.utc)

    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))

        if update_data.list_id is not None:
            cd.list_id = update_data.list_id
            cd.status = "pending"
        if update_data.status is not None:
            cd.status = update_data.status
        if update_data.title is not None:
            cd.title = update_data.title
        if update_data.description is not None:
            cd.description = update_data.description
        if update_data.content is not None:
            cd.content = update_data.content
        if update_data.tags is not None:
            cd.tags = update_data.tags
        if update_data.max_rounds is not None:
            cd.max_rounds = update_data.max_rounds
        if update_data.acceptance_criteria is not None:
            cd.acceptance_criteria = update_data.acceptance_criteria
        cd.updated_at = now

        write_card(Path(idx.file_path), cd)

        # Re-derive project_id from list_id for index sync
        project_id = idx.project_id
        if update_data.list_id is not None:
            sl = session.get(StageList, cd.list_id)
            if sl:
                project_id = sl.project_id
        sync_card_to_index(session, cd, project_id=project_id, file_path=idx.file_path)

    # Dual-write: also update old Card ORM record
    orm_card = session.get(Card, card_id)
    if orm_card:
        if update_data.list_id is not None:
            orm_card.list_id = update_data.list_id
            orm_card.status = "pending"
        if update_data.status is not None:
            orm_card.status = update_data.status
        if update_data.title is not None:
            orm_card.title = update_data.title
        if update_data.description is not None:
            orm_card.description = update_data.description
        if update_data.content is not None:
            orm_card.content = update_data.content
        orm_card.updated_at = now
        session.add(orm_card)

    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    session.commit()
    if orm_card:
        session.refresh(orm_card)
        return orm_card

    # Return from MD data if no ORM card
    cd_final = read_card_md(Path(idx.file_path))
    return Card(
        id=cd_final.id, list_id=cd_final.list_id, title=cd_final.title,
        description=cd_final.description, content=cd_final.content,
        status=cd_final.status, created_at=cd_final.created_at, updated_at=cd_final.updated_at,
    )


# ==========================================
# Delete Card
# ==========================================
@router.delete("/cards/{card_id}")
def delete_card(card_id: int, session: Session = Depends(get_session)):
    # Check status from index or ORM
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)

    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running card")

    # Delete MD file
    if idx and idx.file_path:
        md_path = Path(idx.file_path)
        if md_path.exists():
            md_path.unlink()
        remove_card_from_index(session, card_id)

    # Dual-write: also delete old Card ORM record
    if orm_card:
        session.delete(orm_card)

    session.commit()
    # Clean up lock
    _card_locks.pop(card_id, None)
    return {"ok": True}


@router.delete("/cards/cleanup/duplicates")
def cleanup_duplicate_cards(
    project_id: int,
    dry_run: bool = True,
    session: Session = Depends(get_session)
):
    """清理指定專案的重複卡片（保留每個標題最舊的一張）

    Args:
        project_id: 專案 ID
        dry_run: True=只顯示會刪除的卡片，False=實際刪除
    """
    from sqlmodel import select, func

    # 找出重複的標題
    stmt = (
        select(CardIndex.title, func.min(CardIndex.card_id).label("keep_id"), func.count().label("cnt"))
        .where(CardIndex.project_id == project_id)
        .group_by(CardIndex.title)
        .having(func.count() > 1)
    )
    duplicates = session.exec(stmt).all()

    if not duplicates:
        return {"ok": True, "message": "No duplicates found", "deleted": 0}

    # 收集要刪除的卡片
    cards_to_delete = []
    for title, keep_id, cnt in duplicates:
        # 找出同標題但不是保留的卡片
        dup_cards = session.exec(
            select(CardIndex)
            .where(CardIndex.project_id == project_id)
            .where(CardIndex.title == title)
            .where(CardIndex.card_id != keep_id)
        ).all()
        cards_to_delete.extend(dup_cards)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_delete": len(cards_to_delete),
            "duplicate_titles": len(duplicates),
            "preview": [{"card_id": c.card_id, "title": c.title[:50]} for c in cards_to_delete[:20]]
        }

    # 實際刪除
    deleted_count = 0
    for idx in cards_to_delete:
        if idx.status == "running":
            continue  # 跳過運行中的
        # 刪除 MD 檔案
        if idx.file_path:
            md_path = Path(idx.file_path)
            if md_path.exists():
                md_path.unlink()
        # 刪除 ORM Card
        orm_card = session.get(Card, idx.card_id)
        if orm_card:
            session.delete(orm_card)
        # 刪除 CardIndex
        session.delete(idx)
        _card_locks.pop(idx.card_id, None)
        deleted_count += 1

    session.commit()
    return {"ok": True, "deleted": deleted_count, "duplicate_titles": len(duplicates)}


# ==========================================
# Card Trigger / Abort
# ==========================================
@router.post("/cards/{card_id}/trigger")
def trigger_card(card_id: int, session: Session = Depends(get_session)):
    """手動觸發卡片執行（將 status 設為 pending）"""
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)
    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        raise HTTPException(status_code=409, detail="Card is already running")

    now = datetime.now(timezone.utc)

    # Update MD file + index
    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))
        cd.status = "pending"
        cd.updated_at = now
        write_card(Path(idx.file_path), cd)
        sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)

    # Dual-write: old Card ORM
    if orm_card:
        orm_card.status = "pending"
        orm_card.updated_at = now
        session.add(orm_card)

    session.commit()
    return {"ok": True, "status": "pending"}


@router.post("/cards/{card_id}/abort")
def abort_card(card_id: int, session: Session = Depends(get_session)):
    """中止執行中的任務（透過檔案信號通知 Worker kill 子程序）"""
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)
    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    now = datetime.now(timezone.utc)

    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        # 寫入 abort 檔案信號，Worker 讀取迴圈會檢查並 kill 子程序
        abort_dir = Path(__file__).resolve().parent.parent.parent / ".aegis" / "abort"
        abort_dir.mkdir(parents=True, exist_ok=True)
        (abort_dir / str(card_id)).touch()

        if idx and idx.file_path and Path(idx.file_path).exists():
            cd = read_card_md(Path(idx.file_path))
            cd.status = "failed"
            cd.updated_at = now
            write_card(Path(idx.file_path), cd)
            sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
        if orm_card:
            orm_card.status = "failed"
            orm_card.updated_at = now
            session.add(orm_card)
        session.commit()
    return {"ok": True, "status": "aborted"}


@router.post("/cards/{card_id}/archive")
def archive_card(card_id: int, session: Session = Depends(get_session)):
    """封存卡片（從看板隱藏）"""
    idx = session.get(CardIndex, card_id)
    if not idx or not idx.file_path or not Path(idx.file_path).exists():
        raise HTTPException(status_code=404, detail="Card not found")

    # 運行中的卡片不能封存
    if idx.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="Cannot archive running/pending card")

    cd = read_card_md(Path(idx.file_path))
    cd.is_archived = True
    cd.updated_at = datetime.now(timezone.utc)
    write_card(Path(idx.file_path), cd)
    sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
    session.commit()
    return {"ok": True}


@router.post("/cards/{card_id}/unarchive")
def unarchive_card(card_id: int, session: Session = Depends(get_session)):
    """取消封存卡片"""
    idx = session.get(CardIndex, card_id)
    if not idx or not idx.file_path or not Path(idx.file_path).exists():
        raise HTTPException(status_code=404, detail="Card not found")

    cd = read_card_md(Path(idx.file_path))
    cd.is_archived = False
    cd.updated_at = datetime.now(timezone.utc)
    write_card(Path(idx.file_path), cd)
    sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
    session.commit()
    return {"ok": True}


# ==========================================
# Leader-Worker: Delegate & Subtasks
# ==========================================
class DelegateRequest(BaseModel):
    target_member_id: int
    title: str
    content: Optional[str] = None
    tags: Optional[List[str]] = None


@router.post("/cards/{card_id}/delegate")
def delegate_card(card_id: int, req: DelegateRequest, session: Session = Depends(get_session)):
    """Leader 委派子任務給指定成員（自動建立子卡片並觸發）"""
    from app.models.core import Member, StageList

    # 驗證父卡片存在
    parent_idx = session.get(CardIndex, card_id)
    if not parent_idx:
        raise HTTPException(status_code=404, detail="Parent card not found")

    # 驗證目標成員存在
    member = session.get(Member, req.target_member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Target member not found")

    # 查詢目標成員的 AI inbox（is_member_bound + member_id 綁定的列表）
    inbox = session.exec(
        select(StageList).where(
            StageList.project_id == parent_idx.project_id,
            StageList.member_id == req.target_member_id,
            StageList.is_member_bound == True,  # noqa: E712
        )
    ).first()
    if not inbox:
        raise HTTPException(
            status_code=404,
            detail=f"No inbox list found for member {member.name}"
        )

    # 取得專案資訊
    project = session.get(Project, parent_idx.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 建立子卡片
    new_id = next_card_id(session)
    old_max_id = session.exec(select(sa_func.max(Card.id))).one()
    if old_max_id is not None:
        new_id = max(new_id, old_max_id + 1)

    now = datetime.now(timezone.utc)
    card_data = CardData(
        id=new_id, list_id=inbox.id, title=req.title,
        description=None, content=req.content or "", status="pending",
        tags=req.tags or [], parent_id=card_id,
        created_at=now, updated_at=now,
    )

    # 寫入 MD 檔案
    fpath = card_file_path(project.path, new_id)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)

    # 同步到 index
    sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

    # Dual-write: 建立舊 ORM 記錄
    orm_card = Card(
        id=new_id, list_id=inbox.id, title=req.title,
        description=None, status="pending",
        created_at=now, updated_at=now,
    )
    session.add(orm_card)

    # 記錄委派訊息
    from app.models.core import MemberMessage
    desc_summary = (req.content or "")[:100]
    msg_content = f"委派子任務: {req.title}"
    if desc_summary:
        msg_content += f" — {desc_summary}"
    delegate_msg = MemberMessage(
        from_member_id=parent_idx.member_id or 0,
        to_member_id=req.target_member_id,
        card_id=card_id,
        message_type="delegate",
        content=msg_content,
    )
    session.add(delegate_msg)

    session.commit()
    session.refresh(orm_card)

    return {
        "ok": True,
        "card": {
            "id": new_id,
            "list_id": inbox.id,
            "title": req.title,
            "status": "pending",
            "parent_id": card_id,
            "target_member": member.name,
        }
    }


@router.get("/cards/{card_id}/subtasks")
def get_subtasks(card_id: int, session: Session = Depends(get_session)):
    """查詢卡片的所有子任務"""
    subtasks = session.exec(
        select(CardIndex).where(CardIndex.parent_id == card_id)
    ).all()
    return [
        {
            "card_id": s.card_id,
            "title": s.title,
            "status": s.status,
            "list_id": s.list_id,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in subtasks
    ]


# ==========================================
# Artifacts — workspace 產出物預覽
# ==========================================
_PREVIEW_EXTENSIONS = {
    ".html", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".md", ".mermaid", ".pdf",
}
_EXCLUDED_DIRS = {".claude", "node_modules", "__pycache__", ".git", ".venv", "venv", ".aegis"}

_EXTENSION_TO_PREVIEW: dict[str, str] = {
    ".html": "html", ".svg": "image", ".png": "image", ".jpg": "image",
    ".jpeg": "image", ".gif": "image", ".webp": "image",
    ".md": "markdown", ".mermaid": "markdown", ".pdf": "pdf",
}


def _scan_artifacts(workspace: Path) -> list[dict]:
    """遞迴掃描 workspace 目錄下的可預覽檔案"""
    results: list[dict] = []
    if not workspace.is_dir():
        return results
    for p in workspace.rglob("*"):
        if not p.is_file():
            continue
        # 排除系統目錄
        rel = p.relative_to(workspace)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() not in _PREVIEW_EXTENSIONS:
            continue
        results.append({
            "name": p.name,
            "path": str(rel),
            "type": p.suffix.lower().lstrip("."),
            "size": p.stat().st_size,
            "preview_type": _EXTENSION_TO_PREVIEW.get(p.suffix.lower(), "unknown"),
        })
    # 按名稱排序
    results.sort(key=lambda x: x["name"])
    return results


@router.get("/cards/{card_id}/artifacts")
def list_artifacts(card_id: int):
    """掃描卡片 workspace 目錄下的可預覽產出物"""
    workspace = WORKSPACES_ROOT / f"task-{card_id}"
    return _scan_artifacts(workspace)


@router.get("/cards/{card_id}/artifacts/raw")
def get_artifact_raw(card_id: int, path: str = Query(..., description="workspace 內相對路徑")):
    """取得 workspace 內的原始檔案（供前端 iframe/img 使用）"""
    workspace = WORKSPACES_ROOT / f"task-{card_id}"
    # 安全檢查：解析後路徑必須在 workspace 內
    try:
        target = (workspace / path).resolve()
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not str(target).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@router.get("/cards/{card_id}/broadcast-logs")
def get_card_broadcast_logs(card_id: int, session: Session = Depends(get_session)):
    """取得卡片的廣播記錄（24 小時內）"""
    from app.models.core import BroadcastLog
    logs = session.exec(
        select(BroadcastLog)
        .where(BroadcastLog.card_id == card_id)
        .order_by(BroadcastLog.created_at)
    ).all()
    return [{"line": l.line, "created_at": l.created_at} for l in logs]


@router.get("/cards/{card_id}/cost")
def get_card_cost(card_id: int, session: Session = Depends(get_session)):
    """取得卡片的累計 token 使用量和預估費用"""
    idx = session.get(CardIndex, card_id)
    if not idx:
        raise HTTPException(status_code=404, detail="Card not found")
    return {
        "card_id": card_id,
        "total_input_tokens": idx.total_input_tokens,
        "total_output_tokens": idx.total_output_tokens,
        "estimated_cost_usd": idx.estimated_cost_usd,
    }
