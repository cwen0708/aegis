import pytest
from pathlib import Path
from app.core.member_profile import (
    get_member_dir,
    get_soul_content,
    get_skills_dir,
    get_skills_drafts_dir,
    get_skills_active_dir,
    get_member_memory_dir,
    list_skills,
    get_skill_content,
    find_skill_file,
    approve_skill,
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


def test_get_member_dir_creates_drafts_and_active(tmp_path, monkeypatch):
    """get_member_dir 應該建立 skills/drafts/ 和 skills/active/ 子目錄"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("new-member")
    assert (d / "skills" / "drafts").exists()
    assert (d / "skills" / "active").exists()


def test_list_skills_with_status(tmp_path, monkeypatch):
    """list_skills 應回傳三個位置的 skill，並附正確的 status"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("test-member")

    # root skill → active
    (d / "skills" / "manual.md").write_text("# Manual Skill", encoding="utf-8")
    # active/ skill → active
    (d / "skills" / "active" / "approved.md").write_text("# Approved", encoding="utf-8")
    # drafts/ skill → draft
    (d / "skills" / "drafts" / "pending.md").write_text("# Pending", encoding="utf-8")

    skills = list_skills("test-member")
    by_name = {s["name"]: s for s in skills}

    assert by_name["manual"]["status"] == "active"
    assert by_name["approved"]["status"] == "active"
    assert by_name["pending"]["status"] == "draft"


def test_list_skills_approved_overrides_draft(tmp_path, monkeypatch):
    """同名 skill 在 active/ 和 drafts/ 都存在時，應顯示為 active"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("test-member")
    (d / "skills" / "active" / "foo.md").write_text("# Foo Active", encoding="utf-8")
    (d / "skills" / "drafts" / "foo.md").write_text("# Foo Draft", encoding="utf-8")

    skills = list_skills("test-member")
    by_name = {s["name"]: s for s in skills}
    assert by_name["foo"]["status"] == "active"


def test_get_skill_content_searches_subdirs(tmp_path, monkeypatch):
    """get_skill_content 應依序搜尋 root → active → drafts"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("test-member")

    (d / "skills" / "drafts" / "draft-skill.md").write_text("# Draft", encoding="utf-8")
    (d / "skills" / "active" / "active-skill.md").write_text("# Active", encoding="utf-8")

    assert get_skill_content("test-member", "draft-skill") == "# Draft"
    assert get_skill_content("test-member", "active-skill") == "# Active"
    assert get_skill_content("test-member", "not-exist") == ""


def test_approve_skill_moves_file(tmp_path, monkeypatch):
    """approve_skill 應將檔案從 drafts/ 移至 active/"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("test-member")
    (d / "skills" / "drafts" / "my-skill.md").write_text("# My Skill", encoding="utf-8")

    dest = approve_skill("test-member", "my-skill")

    assert dest == d / "skills" / "active" / "my-skill.md"
    assert dest.exists()
    assert not (d / "skills" / "drafts" / "my-skill.md").exists()


def test_approve_skill_raises_if_not_in_drafts(tmp_path, monkeypatch):
    """若 draft 中找不到 skill，應 raise FileNotFoundError"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    get_member_dir("test-member")

    with pytest.raises(FileNotFoundError):
        approve_skill("test-member", "nonexistent")


def test_find_skill_file_searches_subdirs(tmp_path, monkeypatch):
    """find_skill_file 應搜尋所有子目錄"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    d = get_member_dir("test-member")

    (d / "skills" / "active" / "act.md").write_text("x", encoding="utf-8")
    (d / "skills" / "drafts" / "dft.md").write_text("y", encoding="utf-8")

    assert find_skill_file("test-member", "act") == d / "skills" / "active" / "act.md"
    assert find_skill_file("test-member", "dft") == d / "skills" / "drafts" / "dft.md"
    assert find_skill_file("test-member", "nope") is None
