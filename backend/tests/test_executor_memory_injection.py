"""Tests for executor/memory.py — retrieve_task_memory()"""
import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.executor.memory import retrieve_task_memory


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_vec(value: float, dim: int = 4) -> list[float]:
    """產生指向同一方向的單位化向量，方便控制 cosine similarity。"""
    raw = [value] * dim
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def _make_record(entity_key: str, vector: list[float], slug: str = "xiao-yin"):
    """建立假的 EmbeddingRecord-like 物件。"""
    rec = MagicMock()
    rec.entity_key = entity_key
    rec.member_slug = slug
    rec.vector_json = json.dumps(vector)
    return rec


# ── fixtures ─────────────────────────────────────────────────────────────────

QUERY_VEC = _make_vec(1.0)          # 查詢向量（全正）
HIGH_SIM_VEC = _make_vec(1.0)       # similarity ≈ 1.0（>= 0.7）
MED_SIM_VEC = _make_vec(0.5)        # similarity ≈ 1.0（同方向，>= 0.7）
LOW_SIM_VEC = [1.0, 0.0, 0.0, 0.0] # similarity < 0.7 vs QUERY_VEC
ORTHO_VEC   = [0.0, -1.0, 0.0, 0.0]  # 接近正交，< 0.7


# ── test cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_task_memory_success(tmp_path):
    """正常路徑：回傳通過 threshold 的記憶，並包含正確 content。"""
    mem_file = tmp_path / "memory_a.md"
    mem_file.write_text("記憶內容 A", encoding="utf-8")

    records = [_make_record(str(mem_file), HIGH_SIM_VEC)]

    with (
        patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=QUERY_VEC)),
        patch("app.core.executor.memory._load_embedding_records", return_value=records),
    ):
        result = await retrieve_task_memory("Task Title", "Task Desc", "xiao-yin")

    assert len(result) == 1
    assert result[0]["content"] == "記憶內容 A"
    assert result[0]["similarity"] >= 0.7


@pytest.mark.asyncio
async def test_retrieve_task_memory_similarity_threshold(tmp_path):
    """similarity < 0.7 的記錄應被過濾掉。"""
    high_file = tmp_path / "high.md"
    high_file.write_text("通過門檻的記憶", encoding="utf-8")

    low_file = tmp_path / "low.md"
    low_file.write_text("低相似度記憶（不應出現）", encoding="utf-8")

    records = [
        _make_record(str(high_file), HIGH_SIM_VEC),
        _make_record(str(low_file), ORTHO_VEC),
    ]

    with (
        patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=QUERY_VEC)),
        patch("app.core.executor.memory._load_embedding_records", return_value=records),
    ):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert len(result) == 1
    assert result[0]["content"] == "通過門檻的記憶"


@pytest.mark.asyncio
async def test_retrieve_task_memory_top3(tmp_path):
    """超過 3 條記錄時只回傳 top-3，且按相似度降序排列。"""
    vecs_and_contents = [
        (_make_vec(1.0),  "rank-1"),
        (_make_vec(0.99), "rank-2"),
        (_make_vec(0.98), "rank-3"),
        (_make_vec(0.97), "rank-4-excluded"),
    ]

    records = []
    for i, (vec, text) in enumerate(vecs_and_contents):
        f = tmp_path / f"mem_{i}.md"
        f.write_text(text, encoding="utf-8")
        records.append(_make_record(str(f), vec))

    # query 和所有向量都同方向，相似度都 >= 0.7
    with (
        patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=QUERY_VEC)),
        patch("app.core.executor.memory._load_embedding_records", return_value=records),
    ):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert len(result) == 3
    sims = [r["similarity"] for r in result]
    assert sims == sorted(sims, reverse=True), "結果應按相似度降序排列"


@pytest.mark.asyncio
async def test_retrieve_task_memory_fallback_on_embedding_failure():
    """get_embedding 失敗時應 graceful fallback 回傳 []。"""
    with patch(
        "app.core.executor.memory.get_embedding",
        new=AsyncMock(side_effect=RuntimeError("API timeout")),
    ):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert result == []


@pytest.mark.asyncio
async def test_retrieve_task_memory_fallback_on_empty_embedding():
    """get_embedding 回傳空 list 時應回傳 []。"""
    with patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=[])):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert result == []


@pytest.mark.asyncio
async def test_retrieve_task_memory_fallback_on_db_failure():
    """DB 查詢失敗時應 graceful fallback 回傳 []。"""
    with (
        patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=QUERY_VEC)),
        patch(
            "app.core.executor.memory._load_embedding_records",
            side_effect=Exception("DB connection error"),
        ),
    ):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert result == []


@pytest.mark.asyncio
async def test_retrieve_task_memory_missing_file(tmp_path):
    """entity_key 檔案不存在時，該記錄應被跳過（不 crash）。"""
    missing = tmp_path / "does_not_exist.md"

    with (
        patch("app.core.executor.memory.get_embedding", new=AsyncMock(return_value=QUERY_VEC)),
        patch(
            "app.core.executor.memory._load_embedding_records",
            return_value=[_make_record(str(missing), HIGH_SIM_VEC)],
        ),
    ):
        result = await retrieve_task_memory("Task", "Desc", "xiao-yin")

    assert result == []
