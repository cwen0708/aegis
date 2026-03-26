"""Tests for structured memory CRUD operations."""
import pytest
from datetime import datetime, timezone
from pathlib import Path

from app.core.memory_manager import (
    list_member_memories,
    delete_member_memory,
    update_member_long_term_memory,
    write_member_short_term_memory,
    _parse_frontmatter,
)


@pytest.fixture(autouse=True)
def patch_member_dirs(tmp_path, monkeypatch):
    """Redirect member memory dirs to tmp_path for all tests."""
    st_dir = tmp_path / "short-term"
    lt_dir = tmp_path / "long-term"
    st_dir.mkdir()
    lt_dir.mkdir()
    monkeypatch.setattr(
        "app.core.memory_manager._get_member_short_term_dir",
        lambda slug: st_dir,
    )
    monkeypatch.setattr(
        "app.core.memory_manager._get_member_long_term_dir",
        lambda slug: lt_dir,
    )
    return {"short-term": st_dir, "long-term": lt_dir}


class TestListMemberMemories:
    def test_list_all(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        lt = patch_member_dirs["long-term"]
        # Create a short-term file
        (st / "2026-03-26-120000.md").write_text(
            '---\ntimestamp: "2026-03-26T12:00:00+00:00"\nmember: "test"\n---\n\nshort content',
            encoding="utf-8",
        )
        # Create a long-term file
        (lt / "patterns.md").write_text(
            '---\ntopic: "patterns"\nupdated_at: "2026-03-26T12:00:00+00:00"\n---\n\nlong content',
            encoding="utf-8",
        )
        result = list_member_memories("test", memory_type="all")
        assert len(result) == 2
        types = {r["type"] for r in result}
        assert types == {"short-term", "long-term"}

    def test_list_short_term_only(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        lt = patch_member_dirs["long-term"]
        (st / "2026-03-26-120000.md").write_text("---\n---\n\ncontent", encoding="utf-8")
        (lt / "patterns.md").write_text("---\n---\n\ncontent", encoding="utf-8")
        result = list_member_memories("test", memory_type="short-term")
        assert len(result) == 1
        assert result[0]["type"] == "short-term"

    def test_list_long_term_only(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        lt = patch_member_dirs["long-term"]
        (st / "2026-03-26-120000.md").write_text("---\n---\n\ncontent", encoding="utf-8")
        (lt / "patterns.md").write_text("---\n---\n\ncontent", encoding="utf-8")
        result = list_member_memories("test", memory_type="long-term")
        assert len(result) == 1
        assert result[0]["type"] == "long-term"

    def test_empty_dirs(self, patch_member_dirs):
        result = list_member_memories("test", memory_type="all")
        assert result == []

    def test_frontmatter_parsed(self, patch_member_dirs):
        lt = patch_member_dirs["long-term"]
        (lt / "skills.md").write_text(
            '---\ntopic: "skills"\nupdated_at: "2026-03-26"\ncategory: "skill"\n---\n\nPython expertise',
            encoding="utf-8",
        )
        result = list_member_memories("test", memory_type="long-term")
        assert result[0]["topic"] == "skills"
        assert result[0]["category"] == "skill"
        assert "Python expertise" in result[0]["snippet"]


class TestDeleteMemberMemory:
    def test_delete_short_term(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        f = st / "2026-03-26-120000.md"
        f.write_text("content", encoding="utf-8")
        assert f.exists()
        ok = delete_member_memory("test", "2026-03-26-120000.md")
        assert ok is True
        assert not f.exists()

    def test_delete_long_term(self, patch_member_dirs):
        lt = patch_member_dirs["long-term"]
        f = lt / "patterns.md"
        f.write_text("content", encoding="utf-8")
        ok = delete_member_memory("test", "patterns.md")
        assert ok is True
        assert not f.exists()

    def test_delete_nonexistent(self, patch_member_dirs):
        ok = delete_member_memory("test", "nonexistent.md")
        assert ok is False

    def test_delete_rejects_path_traversal(self, patch_member_dirs):
        ok = delete_member_memory("test", "../etc/passwd")
        assert ok is False

    def test_delete_rejects_slash(self, patch_member_dirs):
        ok = delete_member_memory("test", "sub/file.md")
        assert ok is False


class TestUpdateMemberLongTermMemory:
    def test_create_new(self, patch_member_dirs):
        lt = patch_member_dirs["long-term"]
        path = update_member_long_term_memory("test", "new-topic", "new content")
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "new content" in text
        assert 'topic: "new-topic"' in text
        assert "updated_at:" in text

    def test_update_existing(self, patch_member_dirs):
        lt = patch_member_dirs["long-term"]
        (lt / "existing.md").write_text(
            '---\ntopic: "existing"\nupdated_at: "2026-01-01"\ncategory: "context"\n---\n\nold content',
            encoding="utf-8",
        )
        path = update_member_long_term_memory("test", "existing.md", "updated content")
        text = path.read_text(encoding="utf-8")
        assert "updated content" in text
        assert "old content" not in text
        # Preserves existing category when not specified
        assert 'category: "context"' in text
        # Preserves topic
        assert 'topic: "existing"' in text

    def test_update_with_new_category(self, patch_member_dirs):
        lt = patch_member_dirs["long-term"]
        (lt / "topic.md").write_text(
            '---\ntopic: "topic"\nupdated_at: "2026-01-01"\n---\n\nold',
            encoding="utf-8",
        )
        path = update_member_long_term_memory("test", "topic.md", "new", category="preference")
        text = path.read_text(encoding="utf-8")
        assert 'category: "preference"' in text

    def test_auto_append_md_extension(self, patch_member_dirs):
        path = update_member_long_term_memory("test", "no-ext", "content")
        assert path.name == "no-ext.md"


class TestParseFrontmatter:
    def test_basic(self):
        text = '---\ntopic: "hello"\ncategory: "skill"\n---\n\nbody'
        meta = _parse_frontmatter(text)
        assert meta["topic"] == "hello"
        assert meta["category"] == "skill"

    def test_no_frontmatter(self):
        meta = _parse_frontmatter("just plain text")
        assert meta == {}

    def test_empty_frontmatter(self):
        meta = _parse_frontmatter("---\n---\n\nbody")
        assert meta == {}


class TestWriteShortTermWithCategory:
    def test_category_in_frontmatter(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        # Restore real function for this test
        import app.core.memory_manager as mm
        orig = mm._get_member_short_term_dir
        mm._get_member_short_term_dir = lambda slug: st
        try:
            ts = datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)
            path = write_member_short_term_memory("test", "content", timestamp=ts, category="observation")
            text = path.read_text(encoding="utf-8")
            assert 'category: "observation"' in text
        finally:
            mm._get_member_short_term_dir = orig

    def test_no_category(self, patch_member_dirs):
        st = patch_member_dirs["short-term"]
        import app.core.memory_manager as mm
        mm._get_member_short_term_dir = lambda slug: st
        ts = datetime(2026, 3, 26, 12, 0, 1, tzinfo=timezone.utc)
        path = write_member_short_term_memory("test", "content", timestamp=ts)
        text = path.read_text(encoding="utf-8")
        assert "category:" not in text
