"""Tests for app.core.skill_index (P0-MA-02 step 1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core import skill_index
from app.core.skill_index import (
    SkillMetadata,
    extract_summary,
    load_skill_index,
    parse_frontmatter,
    render_skill_list,
)


# ── parse_frontmatter ─────────────────────────────────────────────────────────

def test_parse_frontmatter_with_description():
    md = "---\ndescription: Aegis API\nalwaysApply: true\n---\n\n# Title\n"
    assert parse_frontmatter(md) == {"description": "Aegis API", "alwaysApply": True}


def test_parse_frontmatter_tags_only_like_ask_member():
    md = "---\ntags:\n  - aegis\n  - project\n---\n\n# 詢問隊友\n"
    assert parse_frontmatter(md) == {"tags": ["aegis", "project"]}


def test_parse_frontmatter_no_frontmatter_or_empty():
    assert parse_frontmatter("# Just a heading\n") == {}
    assert parse_frontmatter("") == {}


def test_parse_frontmatter_malformed_yaml_returns_empty(caplog):
    md = "---\n: : invalid yaml :::\n  bad\n---\n\n# Body\n"
    with caplog.at_level("WARNING"):
        assert parse_frontmatter(md) == {}


def test_parse_frontmatter_is_pure():
    md = "---\ndescription: X\n---\n\n# H\n"
    original = md
    parse_frontmatter(md)
    assert md == original


def test_parse_frontmatter_rejects_no_leading_marker():
    assert parse_frontmatter("some text\n---\nx: 1\n---\n") == {}


# ── extract_summary ──────────────────────────────────────────────────────────

def test_extract_summary_prefers_description_over_summary():
    md = "---\ndescription: DESC\nsummary: SUM\n---\n\n# H\n\nbody\n"
    assert extract_summary(md, parse_frontmatter(md)) == "DESC"


def test_extract_summary_falls_back_to_summary():
    md = "---\nsummary: SUM\n---\n\n# H\n\nbody\n"
    assert extract_summary(md, parse_frontmatter(md)) == "SUM"


def test_extract_summary_falls_back_to_first_paragraph_after_h1():
    md = (
        "---\ntags: [x]\n---\n\n# 詢問隊友\n\n"
        "當你遇到問題時，可以即時諮詢。\n第二行。\n\n## 使用方式\n"
    )
    assert extract_summary(md, parse_frontmatter(md)) == "當你遇到問題時，可以即時諮詢。 第二行。"


def test_extract_summary_empty_when_no_h1_and_no_fm():
    assert extract_summary("just text without heading", {}) == ""


def test_extract_summary_truncates_over_120_chars():
    out = extract_summary("", {"description": "A" * 150})
    assert len(out) == 120 and out.endswith("…")


# ── load_skill_index ─────────────────────────────────────────────────────────

def _make(path: Path, fm: str | None, title: str, body: str = "body text"):
    parts = [f"---\n{fm}\n---\n"] if fm is not None else []
    parts.append(f"\n# {title}\n\n{body}\n")
    path.write_text("".join(parts), encoding="utf-8")


@pytest.fixture
def layout(tmp_path: Path, monkeypatch):
    install_root = tmp_path / "install"
    shared = install_root / ".aegis" / "shared" / "skills"
    shared.mkdir(parents=True)
    member = tmp_path / "members" / "xy" / "skills"
    member.mkdir(parents=True)
    monkeypatch.setattr(skill_index, "get_skills_dir", lambda slug: member)
    return install_root, shared, member


def test_load_member_overrides_shared_keeps_member_scope(layout):
    install_root, shared, member = layout
    _make(shared / "collab.md", "description: shared ver", "共用")
    _make(member / "collab.md", "description: member ver", "成員")
    _make(shared / "api.md", "description: api only", "API")
    idx = load_skill_index("xy", install_root=install_root)
    by_name = {s.name: s for s in idx}
    assert len(idx) == 2
    assert by_name["collab"].summary == "member ver"
    assert by_name["collab"].scope == "member"
    assert by_name["api"].scope == "shared"


def test_load_shared_missing_returns_only_member(tmp_path, monkeypatch):
    install_root = tmp_path / "i"
    install_root.mkdir()
    member = tmp_path / "m" / "skills"
    member.mkdir(parents=True)
    _make(member / "only.md", "description: mine", "X")
    monkeypatch.setattr(skill_index, "get_skills_dir", lambda slug: member)
    idx = load_skill_index("xy", install_root=install_root)
    assert [s.name for s in idx] == ["only"] and idx[0].scope == "member"


def test_load_member_missing_returns_only_shared(tmp_path, monkeypatch):
    install_root = tmp_path / "i"
    shared = install_root / ".aegis" / "shared" / "skills"
    shared.mkdir(parents=True)
    _make(shared / "s1.md", "description: s1", "X")
    monkeypatch.setattr(skill_index, "get_skills_dir", lambda slug: tmp_path / "nope")
    idx = load_skill_index("xy", install_root=install_root)
    assert [s.name for s in idx] == ["s1"] and idx[0].scope == "shared"


def test_load_empty_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_index, "get_skills_dir", lambda slug: tmp_path / "x")
    assert load_skill_index("xy", install_root=tmp_path / "m") == []


def test_load_alwaysapply_from_frontmatter(layout):
    install_root, shared, _ = layout
    _make(shared / "star.md", "description: a\nalwaysApply: true", "S")
    _make(shared / "plain.md", "description: b", "P")
    by_name = {s.name: s for s in load_skill_index("xy", install_root=install_root)}
    assert by_name["star"].alwaysApply is True
    assert by_name["plain"].alwaysApply is False


def test_load_returns_new_list_each_call(layout):
    install_root, shared, _ = layout
    _make(shared / "a.md", "description: a", "A")
    idx1 = load_skill_index("xy", install_root=install_root)
    idx2 = load_skill_index("xy", install_root=install_root)
    assert idx1 is not idx2 and idx1 == idx2


def test_load_invalid_member_slug_does_not_raise(tmp_path, monkeypatch):
    # get_skills_dir 實作會對非法 slug 丟 ValueError；skill_index 應吞掉並只回 shared
    install_root = tmp_path / "i"
    shared = install_root / ".aegis" / "shared" / "skills"
    shared.mkdir(parents=True)
    _make(shared / "s.md", "description: s", "S")

    def _boom(slug):
        raise ValueError("bad slug")

    monkeypatch.setattr(skill_index, "get_skills_dir", _boom)
    idx = load_skill_index("../evil", install_root=install_root)
    assert [s.name for s in idx] == ["s"]


# ── render_skill_list ────────────────────────────────────────────────────────

def test_render_skill_list_format_and_star(tmp_path):
    items = [
        SkillMetadata(name="aegis-api", summary="內部 API", scope="shared",
                      path=tmp_path / "a.md", alwaysApply=True),
        SkillMetadata(name="ask-member", summary="詢問隊友", scope="member",
                      path=tmp_path / "b.md", alwaysApply=False),
    ]
    out = render_skill_list(items)
    assert out.splitlines()[0] == "## Available Skills"
    assert "★ **aegis-api** _(shared)_: 內部 API" in out
    assert "- **ask-member** _(member)_: 詢問隊友" in out
    assert "★ **ask-member**" not in out


def test_render_skill_list_empty():
    out = render_skill_list([])
    assert "## Available Skills" in out and "_(無)_" in out


def test_render_skill_list_handles_empty_summary(tmp_path):
    items = [SkillMetadata(name="x", summary="", scope="shared",
                           path=tmp_path / "x.md", alwaysApply=False)]
    out = render_skill_list(items)
    assert "**x**" in out and "_(無描述)_" in out
