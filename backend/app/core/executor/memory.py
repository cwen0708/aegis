"""executor/memory.py — 任務啟動時的記憶查詢模組。"""
import json
import logging
from pathlib import Path
from typing import Optional

from app.core.embedding import get_embedding, cosine_similarity

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.7
_TOP_K = 3


async def retrieve_task_memory(
    card_title: str,
    card_description: str,
    member_slug: str,
) -> list[dict]:
    """查詢與任務相關的歷史記憶，供注入 system prompt 使用。

    Args:
        card_title: 卡片標題
        card_description: 卡片描述
        member_slug: 成員 slug（用於過濾 EmbeddingRecord）

    Returns:
        List[dict] = [{"content": "...", "similarity": 0.85}, ...]
        失敗時回傳 []
    """
    query_text = f"{card_title}\n{card_description}".strip()
    try:
        query_vector = await get_embedding(query_text)
    except Exception as e:
        logger.warning(f"[executor.memory] get_embedding failed: {e}")
        return []

    if not query_vector:
        logger.warning("[executor.memory] Empty embedding returned, skipping retrieval")
        return []

    try:
        records = _load_embedding_records(member_slug)
    except Exception as e:
        logger.warning(f"[executor.memory] DB query failed: {e}")
        return []

    scored = []
    for rec in records:
        try:
            vec = json.loads(rec.vector_json)
        except (json.JSONDecodeError, TypeError):
            continue

        sim = cosine_similarity(query_vector, vec)
        if sim >= _SIMILARITY_THRESHOLD:
            content = _read_entity_content(rec.entity_key)
            if content:
                scored.append({"content": content, "similarity": round(sim, 4)})

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:_TOP_K]


def _load_embedding_records(member_slug: str):
    """從 DB 載入指定成員的 memory 類型 EmbeddingRecord。"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import EmbeddingRecord

    with Session(engine) as session:
        return session.exec(
            select(EmbeddingRecord).where(
                EmbeddingRecord.member_slug == member_slug,
                EmbeddingRecord.entity_type == "memory",
            )
        ).all()


def _read_entity_content(entity_key: str) -> Optional[str]:
    """讀取 entity_key 對應的檔案內容，失敗回傳 None。"""
    try:
        path = Path(entity_key)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"[executor.memory] Failed to read {entity_key}: {e}")
    return None
