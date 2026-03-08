import pytest
from pathlib import Path
from app.core.member_profile import (
    get_member_dir,
    get_soul_content,
    get_skills_dir,
    get_member_memory_dir,
    MEMBERS_ROOT,
)


@pytest.fixture
def member_dir(tmp_path, monkeypatch):
    """Patch MEMBERS_ROOT to use tmp_path"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    slug = "test-member"
    d = tmp_path / slug
    d.mkdir()
    return d, slug


def test_get_member_dir(member_dir):
    d, slug = member_dir
    result = get_member_dir(slug)
    assert result == d
    assert result.exists()


def test_get_member_dir_creates_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    result = get_member_dir("new-member")
    assert result.exists()
    assert (result / "skills").exists()
    assert (result / "memory" / "short-term").exists()
    assert (result / "memory" / "long-term").exists()


def test_get_soul_content(member_dir):
    d, slug = member_dir
    soul_text = "# Test Soul\n\nYou are a test agent."
    (d / "soul.md").write_text(soul_text, encoding="utf-8")
    assert get_soul_content(slug) == soul_text


def test_get_soul_content_missing(member_dir):
    _, slug = member_dir
    assert get_soul_content(slug) == ""


def test_get_skills_dir(member_dir):
    d, slug = member_dir
    skills = d / "skills"
    skills.mkdir()
    (skills / "python.md").write_text("# Python", encoding="utf-8")
    result = get_skills_dir(slug)
    assert result == skills
    assert list(result.glob("*.md")) != []


def test_get_member_memory_dir(member_dir):
    d, slug = member_dir
    mem = get_member_memory_dir(slug)
    assert mem == d / "memory"
    assert (mem / "short-term").exists()
    assert (mem / "long-term").exists()
