import pytest
from pathlib import Path
from app.core.memory_manager import (
    write_member_short_term_memory,
    read_member_short_term_memories,
    cleanup_member_short_term,
)


@pytest.fixture
def member_mem(tmp_path, monkeypatch):
    """Patch MEMBERS_ROOT so memory writes go to tmp_path"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    slug = "test-dev"
    mem = tmp_path / slug / "memory"
    (mem / "short-term").mkdir(parents=True)
    (mem / "long-term").mkdir(parents=True)
    return slug


def test_write_member_short_term(member_mem):
    path = write_member_short_term_memory(member_mem, "Task completed successfully")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Task completed successfully" in content
    assert path.parent.name == "short-term"


def test_read_member_short_term(member_mem):
    write_member_short_term_memory(member_mem, "Memory entry 1")
    result = read_member_short_term_memories(member_mem, days=7)
    assert "Memory entry 1" in result


def test_read_member_short_term_empty(member_mem):
    result = read_member_short_term_memories(member_mem, days=7)
    assert "no recent" in result
