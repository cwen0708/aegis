"""Tests for memory_manager module."""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.core.memory_manager import (
    get_memory_dir,
    get_short_term_dir,
    get_long_term_dir,
    write_short_term_memory,
    write_long_term_memory,
    read_short_term_memories,
    read_long_term_memories,
    parse_memory_output,
    process_memory_output,
    cleanup_short_term,
)


class TestWriteShortTermMemory:
    def test_creates_file_with_correct_name(self, tmp_path):
        ts = datetime(2026, 3, 7, 8, 0, tzinfo=timezone.utc)
        path = write_short_term_memory(str(tmp_path), "test content", timestamp=ts)

        assert path.name == "2026-03-07-0800.md"
        assert path.exists()

    def test_file_contains_frontmatter_and_content(self, tmp_path):
        ts = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
        path = write_short_term_memory(str(tmp_path), "Hello world", timestamp=ts)
        text = path.read_text(encoding="utf-8")

        assert 'timestamp: "2026-03-07T12:00:00+00:00"' in text
        assert "period:" in text
        assert "Hello world" in text

    def test_default_timestamp_is_now(self, tmp_path):
        path = write_short_term_memory(str(tmp_path), "auto ts")
        assert path.exists()
        # Filename should be today-ish
        assert path.suffix == ".md"


class TestWriteLongTermMemory:
    def test_creates_file(self, tmp_path):
        path = write_long_term_memory(str(tmp_path), "patterns here", "system-patterns")
        assert path.name == "system-patterns.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "patterns here" in text
        assert 'topic: "system-patterns"' in text

    def test_overwrites_existing(self, tmp_path):
        write_long_term_memory(str(tmp_path), "v1", "notes.md")
        path = write_long_term_memory(str(tmp_path), "v2", "notes.md")
        text = path.read_text(encoding="utf-8")
        assert "v2" in text
        assert "v1" not in text

    def test_appends_md_extension(self, tmp_path):
        path = write_long_term_memory(str(tmp_path), "x", "foo")
        assert path.name == "foo.md"


class TestReadShortTermMemories:
    def test_reads_recent_files(self, tmp_path):
        now = datetime.now(timezone.utc)
        write_short_term_memory(str(tmp_path), "recent entry", timestamp=now)
        result = read_short_term_memories(str(tmp_path), days=7)
        assert "recent entry" in result

    def test_skips_old_files(self, tmp_path):
        old = datetime.now(timezone.utc) - timedelta(days=30)
        write_short_term_memory(str(tmp_path), "old entry", timestamp=old)
        result = read_short_term_memories(str(tmp_path), days=7)
        assert result == "(no recent short-term memories)"

    def test_empty_directory(self, tmp_path):
        result = read_short_term_memories(str(tmp_path), days=7)
        assert result == "(no recent short-term memories)"


class TestReadLongTermMemories:
    def test_reads_all_files(self, tmp_path):
        write_long_term_memory(str(tmp_path), "pattern A", "system-patterns")
        write_long_term_memory(str(tmp_path), "issue B", "recurring-issues")
        result = read_long_term_memories(str(tmp_path))
        assert "pattern A" in result
        assert "issue B" in result

    def test_empty_directory(self, tmp_path):
        result = read_long_term_memories(str(tmp_path))
        assert result == "(no long-term memories yet)"


class TestParseMemoryOutput:
    def test_full_format(self):
        ai_output = (
            "---SHORT_TERM---\n"
            "short content here\n"
            "---LONG_TERM---\n"
            "long content here\n"
            "---LONG_TERM_FILE---\n"
            "recurring-issues.md"
        )
        result = parse_memory_output(ai_output)
        assert result["short_term"] == "short content here"
        assert result["long_term"] == "long content here"
        assert result["long_term_file"] == "recurring-issues.md"

    def test_short_term_only(self):
        ai_output = "---SHORT_TERM---\njust short stuff"
        result = parse_memory_output(ai_output)
        assert result["short_term"] == "just short stuff"
        assert result["long_term"] == ""
        assert result["long_term_file"] == ""

    def test_no_delimiters(self):
        ai_output = "raw text with no markers"
        result = parse_memory_output(ai_output)
        assert result["short_term"] == "raw text with no markers"
        assert result["long_term"] == ""

    def test_long_term_without_file(self):
        ai_output = (
            "---SHORT_TERM---\nshort\n"
            "---LONG_TERM---\nlong stuff"
        )
        result = parse_memory_output(ai_output)
        assert result["short_term"] == "short"
        assert result["long_term"] == "long stuff"
        assert result["long_term_file"] == ""


class TestProcessMemoryOutput:
    def test_end_to_end(self, tmp_path):
        ai_output = (
            "---SHORT_TERM---\n"
            "deploy went well\n"
            "---LONG_TERM---\n"
            "always check env vars\n"
            "---LONG_TERM_FILE---\n"
            "recurring-issues.md"
        )
        written = process_memory_output(str(tmp_path), ai_output)
        assert "short_term" in written
        assert "long_term" in written
        assert Path(written["short_term"]).exists()
        assert Path(written["long_term"]).exists()

    def test_no_long_term_update(self, tmp_path):
        ai_output = (
            "---SHORT_TERM---\n"
            "nothing special\n"
            "---LONG_TERM---\n"
            "no update needed"
        )
        written = process_memory_output(str(tmp_path), ai_output)
        assert "short_term" in written
        assert "long_term" not in written

    def test_defaults_long_term_filename(self, tmp_path):
        ai_output = (
            "---SHORT_TERM---\nstuff\n"
            "---LONG_TERM---\nimportant observation"
        )
        written = process_memory_output(str(tmp_path), ai_output)
        assert "general-observations.md" in written["long_term"]


class TestCleanupShortTerm:
    def test_deletes_old_keeps_recent(self, tmp_path):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=60)
        recent = now - timedelta(days=5)

        write_short_term_memory(str(tmp_path), "old", timestamp=old)
        write_short_term_memory(str(tmp_path), "recent", timestamp=recent)

        deleted = cleanup_short_term(str(tmp_path), retention_days=30)
        assert deleted == 1

        # Recent file should still exist
        st_dir = tmp_path / "memory" / "short-term"
        remaining = list(st_dir.glob("*.md"))
        assert len(remaining) == 1
        assert "recent" in remaining[0].read_text(encoding="utf-8")

    def test_nothing_to_delete(self, tmp_path):
        now = datetime.now(timezone.utc)
        write_short_term_memory(str(tmp_path), "fresh", timestamp=now)
        deleted = cleanup_short_term(str(tmp_path), retention_days=30)
        assert deleted == 0
