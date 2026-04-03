"""卡片歷史執行記錄 API — GET /cards/{card_id}/history"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime, timezone, timedelta
from app.database import get_session
from app.models.core import CardIndex, TaskLog

router = APIRouter(tags=["History"])


@router.get("/cards/{card_id}/history")
def get_card_history(
    card_id: int,
    days: int = Query(default=7, ge=1, le=365, description="查詢最近幾天的記錄"),
    limit: int = Query(default=10, ge=1, le=100, description="最多回傳幾筆"),
    session: Session = Depends(get_session),
):
    """查詢卡片的歷史執行記錄（含 token 用量與費用）"""
    # 確認卡片存在
    idx = session.get(CardIndex, card_id)
    if not idx:
        raise HTTPException(status_code=404, detail="Card not found")

    # 查詢 TaskLog（依時間篩選 + 限制筆數）
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logs = session.exec(
        select(TaskLog)
        .where(TaskLog.card_id == card_id)
        .where(TaskLog.created_at >= cutoff)
        .order_by(TaskLog.created_at.desc())
        .limit(limit)
    ).all()

    # 累計統計
    total_input = sum(l.input_tokens for l in logs)
    total_output = sum(l.output_tokens for l in logs)
    total_cost = sum(l.cost_usd for l in logs)

    return {
        "card_id": card_id,
        "card_title": idx.title,
        "days": days,
        "total_runs": len(logs),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "runs": [
            {
                "id": l.id,
                "status": l.status,
                "provider": l.provider,
                "model": l.model,
                "member_id": l.member_id,
                "input_tokens": l.input_tokens,
                "output_tokens": l.output_tokens,
                "cache_read_tokens": l.cache_read_tokens,
                "cache_creation_tokens": l.cache_creation_tokens,
                "cost_usd": l.cost_usd,
                "duration_ms": l.duration_ms,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
    }
