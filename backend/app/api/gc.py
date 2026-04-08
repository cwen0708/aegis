"""GC API — 技術債掃描端點"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.gc_scheduler import schedule_gc_scan
from app.database import get_session
from app.models.core import Project

logger = logging.getLogger(__name__)

router = APIRouter(tags=["GC"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class GCScanRequest(BaseModel):
    project_id: int


class GCScanFinding(BaseModel):
    id: int | None = None
    title: str
    status: str
    tags: list[str]


class GCScanResponse(BaseModel):
    project_id: int
    cards_created: int
    cards: list[GCScanFinding]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.post("/gc/scan", response_model=GCScanResponse)
def trigger_gc_scan(req: GCScanRequest, session: Session = Depends(get_session)):
    """手動觸發技術債掃描，回傳新建的卡片清單。"""
    project = session.get(Project, req.project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project {req.project_id} not found",
        )
    if not project.path:
        raise HTTPException(
            status_code=400,
            detail=f"Project {req.project_id} has no path configured",
        )

    cards = schedule_gc_scan(req.project_id, project.path)

    return GCScanResponse(
        project_id=req.project_id,
        cards_created=len(cards),
        cards=[
            GCScanFinding(
                id=c.id,
                title=c.title,
                status=c.status,
                tags=c.tags or [],
            )
            for c in cards
        ],
    )
