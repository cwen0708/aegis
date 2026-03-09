import pytest
from pathlib import Path
from app.core.task_workspace import (
    prepare_workspace,
    cleanup_workspace,
    WORKSPACES_ROOT,
    PROVIDER_CONFIG,
)


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """Patch WORKSPACES_ROOT and MEMBERS_ROOT to tmp dirs"""
    monkeypatch.setattr("app.core.task_workspace.WORKSPACES_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path / "members")
    return tmp_path


def _setup_member(ws_root, slug="test-dev"):
    """Helper: create a member profile with soul + skills"""
    member_dir = ws_root / "members" / slug
    member_dir.mkdir(parents=True)
    (member_dir / "soul.md").write_text("# Test Dev\nYou are a test developer.", encoding="utf-8")
    skills_dir = member_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "python.md").write_text("# Python best practices", encoding="utf-8")
    (skills_dir / "testing.md").write_text("# Testing guidelines", encoding="utf-8")
    mem_dir = member_dir / "memory"
    (mem_dir / "short-term").mkdir(parents=True)
    (mem_dir / "long-term").mkdir(parents=True)
    return slug


def test_prepare_workspace_claude(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=42,
        member_slug=slug,
        provider="claude",
        project_path="/fake/project",
        card_content="## Task\nDo something",
    )
    assert ws.exists()
    # CLAUDE.md should exist
    claude_md = ws / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text(encoding="utf-8")
    assert "/fake/project" in content
    assert "Test Dev" in content
    assert "Do something" in content
    assert "memory" in content.lower()
    # skills copied
    skills_dir = ws / ".claude" / "skills"
    assert skills_dir.exists()
    assert (skills_dir / "python.md").exists()
    assert (skills_dir / "testing.md").exists()


def test_prepare_workspace_gemini(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=99,
        member_slug=slug,
        provider="gemini",
        project_path="/fake/project",
        card_content="## Task\nGemini task",
    )
    # Gemini.md should exist (not CLAUDE.md)
    assert (ws / "Gemini.md").exists()
    assert not (ws / "CLAUDE.md").exists()
    # skills in .gemini/skills/
    assert (ws / ".gemini" / "skills" / "python.md").exists()


def test_cleanup_workspace(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=7, member_slug=slug, provider="claude",
        project_path="/x", card_content="test",
    )
    assert ws.exists()
    cleanup_workspace(7)
    assert not ws.exists()


def test_cleanup_workspace_nonexistent(ws_root):
    """Should not raise even if workspace doesn't exist"""
    cleanup_workspace(999)


def test_prepare_workspace_no_skills(ws_root):
    """Member with soul but no skills should still work"""
    slug = "no-skills"
    member_dir = ws_root / "members" / slug
    member_dir.mkdir(parents=True)
    (member_dir / "soul.md").write_text("# Solo\nNo skills.", encoding="utf-8")
    (member_dir / "skills").mkdir()
    (member_dir / "memory" / "short-term").mkdir(parents=True)
    (member_dir / "memory" / "long-term").mkdir(parents=True)
    ws = prepare_workspace(
        card_id=1, member_slug=slug, provider="claude",
        project_path="/x", card_content="test",
    )
    assert (ws / "CLAUDE.md").exists()
    assert (ws / ".claude" / "skills").exists()
