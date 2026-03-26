"""Embedding 向量基礎設施 — OpenAI text-embedding-3-small + cosine similarity."""
import hashlib
import json
import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _get_openai_api_key() -> str:
    """取得 OpenAI API Key：優先 env，再查 ProjectEnvVar。"""
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    try:
        from sqlmodel import Session, select
        from app.database import engine
        from app.models.core import ProjectEnvVar
        with Session(engine) as session:
            row = session.exec(
                select(ProjectEnvVar).where(ProjectEnvVar.key == "OPENAI_API_KEY")
            ).first()
            if row:
                return row.value
    except Exception as e:
        logger.warning(f"[embedding] Failed to query ProjectEnvVar: {e}")
    return ""


async def get_embedding(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """呼叫 OpenAI Embeddings API，失敗回傳空 list。"""
    api_key = _get_openai_api_key()
    if not api_key:
        logger.warning("[embedding] No OPENAI_API_KEY available")
        return []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"input": text[:8000], "model": model},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        logger.warning(f"[embedding] get_embedding failed: {e}")
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """純 Python cosine similarity，空向量回傳 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def content_hash(text: str) -> str:
    """SHA256[:16] 的內容指紋。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def embed_and_store(
    entity_type: str,
    entity_key: str,
    content: str,
    member_slug: Optional[str] = None,
) -> bool:
    """計算 embedding 並存入 EmbeddingRecord，hash 未變則跳過。"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import EmbeddingRecord

    new_hash = content_hash(content)

    with Session(engine) as session:
        existing = session.exec(
            select(EmbeddingRecord).where(
                EmbeddingRecord.entity_type == entity_type,
                EmbeddingRecord.entity_key == entity_key,
            )
        ).first()

        if existing and existing.content_hash == new_hash:
            return True  # 內容沒變，跳過

        vector = await get_embedding(content)
        if not vector:
            return False

        if existing:
            existing.content_hash = new_hash
            existing.vector_json = json.dumps(vector)
            existing.member_slug = member_slug
            session.add(existing)
        else:
            record = EmbeddingRecord(
                entity_type=entity_type,
                entity_key=entity_key,
                member_slug=member_slug,
                content_hash=new_hash,
                vector_json=json.dumps(vector),
            )
            session.add(record)
        session.commit()
    logger.info(f"[embedding] Stored embedding for {entity_type}:{entity_key}")
    return True


def search_similar(
    query_vector: list[float],
    member_slug: str,
    top_k: int = 5,
) -> list[dict]:
    """載入 member 所有 EmbeddingRecord，cosine 排序回傳 top_k。"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import EmbeddingRecord

    with Session(engine) as session:
        records = session.exec(
            select(EmbeddingRecord).where(
                EmbeddingRecord.member_slug == member_slug,
                EmbeddingRecord.entity_type == "memory",
            )
        ).all()

    results = []
    for rec in records:
        try:
            vec = json.loads(rec.vector_json)
        except (json.JSONDecodeError, TypeError):
            continue
        sim = cosine_similarity(query_vector, vec)
        if sim > 0:
            results.append({
                "entity_key": rec.entity_key,
                "score": round(sim, 4),
                "entity_type": rec.entity_type,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]
