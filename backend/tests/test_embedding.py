"""Tests for embedding module — cosine similarity, content hash, model instantiation."""
import math
from app.core.embedding import cosine_similarity, content_hash
from app.models.core import EmbeddingRecord


def test_cosine_similarity_identical():
    """相同向量 → 1.0"""
    vec = [1.0, 2.0, 3.0, 4.0]
    assert math.isclose(cosine_similarity(vec, vec), 1.0, rel_tol=1e-6)


def test_cosine_similarity_orthogonal():
    """正交向量 → 0.0"""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert math.isclose(cosine_similarity(a, b), 0.0, abs_tol=1e-9)


def test_cosine_similarity_empty():
    """空向量 → 0.0"""
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], []) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0


def test_content_hash_deterministic():
    """相同內容產生相同 hash"""
    text = "Aegis 記憶系統測試"
    h1 = content_hash(text)
    h2 = content_hash(text)
    assert h1 == h2
    assert len(h1) == 16
    # 不同內容不同 hash
    assert content_hash("other") != h1


def test_embedding_record_model():
    """EmbeddingRecord 可正常實例化"""
    rec = EmbeddingRecord(
        entity_type="memory",
        entity_key="/path/to/file.md",
        member_slug="xiao-yin",
        content_hash="abc123",
        vector_json="[0.1, 0.2, 0.3]",
    )
    assert rec.entity_type == "memory"
    assert rec.entity_key == "/path/to/file.md"
    assert rec.member_slug == "xiao-yin"
    assert rec.model_name == "text-embedding-3-small"
    assert rec.dimension == 1536
