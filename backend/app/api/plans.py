"""Plans API — Execution Plan 版本化查詢"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.plan_store import list_plans, load_plan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Plans"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class PlanInfo(BaseModel):
    round_num: int
    filename: str


class PlanListResponse(BaseModel):
    card_id: int
    plans: list[PlanInfo]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get("/plans/{card_id}", response_model=PlanListResponse)
def list_card_plans(card_id: int):
    """列出某卡片的所有 plan 版本。"""
    entries = list_plans(card_id)
    return PlanListResponse(
        card_id=card_id,
        plans=[
            PlanInfo(round_num=e.round_num, filename=e.path.name)
            for e in entries
        ],
    )


class PlanContentResponse(BaseModel):
    card_id: int
    round_num: int
    content: str


@router.get("/plans/{card_id}/{round_num}", response_model=PlanContentResponse)
def get_card_plan(card_id: int, round_num: int):
    """取得特定版本的 plan 內容。"""
    text = load_plan(card_id, round_num)
    if text is None:
        raise HTTPException(
            status_code=404,
            detail=f"Plan not found: card={card_id} round={round_num}",
        )
    return PlanContentResponse(card_id=card_id, round_num=round_num, content=text)
