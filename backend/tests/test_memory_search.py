"""Tests for BM25 + time-decay memory search."""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from app.core.memory_manager import search_member_memories, _tokenize


# ── Helpers ──

def _write_memory(directory: Path, filename: str, content: str) -> Path:
    """在指定目錄寫入一份記憶檔。"""
    directory.mkdir(parents=True, exist_ok=True)
    fpath = directory / filename
    fpath.write_text(content, encoding="utf-8")
    return fpath


def _make_frontmatter(content: str, timestamp: str = "") -> str:
    """產生帶 frontmatter 的記憶內容。"""
    fm = f'---\ntimestamp: "{timestamp}"\n---\n\n' if timestamp else ""
    return fm + content


# ── _tokenize 基本測試 ──

class TestTokenize:
    def test_english(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_chinese(self):
        tokens = _tokenize("部署成功")
        assert tokens == ["部", "署", "成", "功"]

    def test_mixed(self):
        tokens = _tokenize("deploy 部署 ok")
        assert "deploy" in tokens
        assert "ok" in tokens
        assert "部" in tokens

    def test_empty(self):
        assert _tokenize("") == []
        assert _tokenize("   !!!") == []


# ── BM25 分數排序 ──

class TestBM25Ordering:
    """驗證包含更多查詢關鍵字的文件排序較前。"""

    def test_relevant_doc_ranks_higher(self, tmp_path):
        """含更多關鍵字的文件應獲得更高 BM25 分數。"""
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)
        # 兩份相同日期的記憶，關鍵字密度不同
        fname = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, fname, "deploy deploy deploy success production deploy")

        fname2 = (now - timedelta(seconds=1)).strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, fname2, "nothing interesting happened today weather nice")

        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "deploy", top_k=5)

        assert len(results) == 1  # 只有含 deploy 的文件有分數
        assert results[0]["score"] > 0

    def test_multiple_query_terms(self, tmp_path):
        """多關鍵字查詢：同時包含兩個字的文件排名更高。"""
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)

        # doc1: 含 deploy + error 兩個字
        f1 = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, f1, "deploy failed with error on server")

        # doc2: 只含 deploy
        f2 = (now - timedelta(seconds=1)).strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, f2, "deploy completed successfully on staging")

        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "deploy error", top_k=5)

        assert len(results) == 2
        # 包含兩個關鍵字的文件應排在前面
        assert "error" in results[0]["snippet"].lower()


# ── 時間衰減 ──

class TestTimeDecay:
    """驗證較新的記憶在相同 BM25 分數下排序更前。"""

    def test_newer_memory_scores_higher(self, tmp_path):
        """內容相同時，較新的記憶因時間衰減較小而分數更高。"""
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)
        old = now - timedelta(days=14)  # 14 天前 → 衰減 0.5^2 = 0.25

        # 新記憶
        new_fname = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, new_fname, "critical deploy failure on production")

        # 舊記憶（同樣內容）
        old_fname = old.strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, old_fname, "critical deploy failure on production")

        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "deploy failure", top_k=5)

        assert len(results) == 2
        # 較新的應排第一（分數更高）
        assert results[0]["score"] > results[1]["score"]
        # 確認分數比例大約是 4:1（14 天 = 2 個半衰期）
        ratio = results[0]["score"] / results[1]["score"]
        assert ratio > 3.0  # 容許一些浮點誤差


# ── 空查詢 ──

class TestEmptyQuery:
    def test_empty_string_returns_empty(self, tmp_path):
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"
        st_dir.mkdir(parents=True, exist_ok=True)
        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            assert search_member_memories("test-member", "") == []
            assert search_member_memories("test-member", "   ") == []

    def test_no_matching_docs_returns_empty(self, tmp_path):
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)
        fname = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
        _write_memory(st_dir, fname, "nothing relevant here at all")
        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "kubernetes", top_k=5)
            assert results == []


# ── Snippet 與 Frontmatter ──

class TestSnippet:
    def test_frontmatter_stripped_from_snippet(self, tmp_path):
        """snippet 應跳過 YAML frontmatter。"""
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)
        fname = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
        content = _make_frontmatter("deploy log content here", now.isoformat())
        _write_memory(st_dir, fname, content)
        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "deploy", top_k=5)

        assert len(results) == 1
        assert results[0]["snippet"].startswith("deploy log content")
        assert "---" not in results[0]["snippet"]


# ── top_k 限制 ──

class TestTopK:
    def test_respects_top_k(self, tmp_path):
        st_dir = tmp_path / "memory" / "short-term"
        lt_dir = tmp_path / "memory" / "long-term"

        now = datetime.now(timezone.utc)
        for i in range(10):
            fname = (now - timedelta(seconds=i)).strftime("%Y-%m-%d-%H%M%S") + ".md"
            _write_memory(st_dir, fname, f"deploy attempt {i} on production server")

        lt_dir.mkdir(parents=True, exist_ok=True)

        with patch("app.core.memory_manager._get_member_short_term_dir", return_value=st_dir), \
             patch("app.core.memory_manager._get_member_long_term_dir", return_value=lt_dir):
            results = search_member_memories("test-member", "deploy", top_k=3)

        assert len(results) == 3
