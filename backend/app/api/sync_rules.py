"""SyncRule CRUD API — 欄位級同步規則管理"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_session
from app.models.core import SyncRule

router = APIRouter(tags=["SyncRules"])


# ==========================================
# Schemas
# ==========================================
class SyncRuleResponse(BaseModel):
    id: int
    entity_type: str
    field_name: str
    writable_by: str
    conflict_strategy: str
    is_enabled: bool


class SyncRuleCreateRequest(BaseModel):
    entity_type: str
    field_name: str
    writable_by: str = "both"
    conflict_strategy: str = "last_write_wins"
    is_enabled: bool = True


class SyncRuleUpdateRequest(BaseModel):
    writable_by: Optional[str] = None
    conflict_strategy: Optional[str] = None
    is_enabled: Optional[bool] = None


# ==========================================
# Allowed values
# ==========================================
_WRITABLE_BY_VALUES = {"ai", "human", "both"}
_CONFLICT_STRATEGY_VALUES = {"last_write_wins", "human_wins", "ai_wins", "manual_merge", "ai_merge"}


# ==========================================
# Endpoints
# ==========================================
@router.get("/sync-rules", response_model=List[SyncRuleResponse])
def list_sync_rules(
    entity_type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """列出所有同步規則，可選 entity_type 過濾。"""
    stmt = select(SyncRule)
    if entity_type:
        stmt = stmt.where(SyncRule.entity_type == entity_type)
    stmt = stmt.order_by(SyncRule.entity_type, SyncRule.field_name)
    return session.exec(stmt).all()


@router.get("/sync-rules/{entity_type}", response_model=List[SyncRuleResponse])
def get_sync_rules_by_entity(
    entity_type: str,
    session: Session = Depends(get_session),
):
    """取得特定實體類型的同步規則列表。"""
    rules = session.exec(
        select(SyncRule)
        .where(SyncRule.entity_type == entity_type)
        .order_by(SyncRule.field_name)
    ).all()
    return rules


@router.put("/sync-rules/{rule_id}", response_model=SyncRuleResponse)
def update_sync_rule(
    rule_id: int,
    req: SyncRuleUpdateRequest,
    session: Session = Depends(get_session),
):
    """更新同步規則的 writable_by / conflict_strategy / is_enabled。"""
    rule = session.get(SyncRule, rule_id)
    if not rule:
        raise HTTPException(404, f"SyncRule #{rule_id} not found")

    if req.writable_by is not None:
        if req.writable_by not in _WRITABLE_BY_VALUES:
            raise HTTPException(422, f"writable_by must be one of {_WRITABLE_BY_VALUES}")
        rule.writable_by = req.writable_by

    if req.conflict_strategy is not None:
        if req.conflict_strategy not in _CONFLICT_STRATEGY_VALUES:
            raise HTTPException(422, f"conflict_strategy must be one of {_CONFLICT_STRATEGY_VALUES}")
        rule.conflict_strategy = req.conflict_strategy

    if req.is_enabled is not None:
        rule.is_enabled = req.is_enabled

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.post("/sync-rules", response_model=SyncRuleResponse, status_code=201)
def create_sync_rule(
    req: SyncRuleCreateRequest,
    session: Session = Depends(get_session),
):
    """建立新的同步規則（entity_type + field_name 不可重複）。"""
    if req.writable_by not in _WRITABLE_BY_VALUES:
        raise HTTPException(422, f"writable_by must be one of {_WRITABLE_BY_VALUES}")
    if req.conflict_strategy not in _CONFLICT_STRATEGY_VALUES:
        raise HTTPException(422, f"conflict_strategy must be one of {_CONFLICT_STRATEGY_VALUES}")

    existing = session.exec(
        select(SyncRule).where(
            SyncRule.entity_type == req.entity_type,
            SyncRule.field_name == req.field_name,
        )
    ).first()
    if existing:
        raise HTTPException(
            409,
            f"SyncRule for {req.entity_type}.{req.field_name} already exists (id={existing.id})",
        )

    rule = SyncRule(
        entity_type=req.entity_type,
        field_name=req.field_name,
        writable_by=req.writable_by,
        conflict_strategy=req.conflict_strategy,
        is_enabled=req.is_enabled,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.delete("/sync-rules/{rule_id}", status_code=204)
def delete_sync_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    """刪除指定的同步規則。"""
    rule = session.get(SyncRule, rule_id)
    if not rule:
        raise HTTPException(404, f"SyncRule #{rule_id} not found")
    session.delete(rule)
    session.commit()
