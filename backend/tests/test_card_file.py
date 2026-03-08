from datetime import datetime, timezone
from app.core.card_file import (
    CardData, read_card, write_card, card_file_path,
    serialize_card, validate_frontmatter, VALID_STATUSES,
)


def _make_card(**overrides):
    defaults = dict(
        id=42, list_id=5, title="Fix SQLite pool", description="Serious bug",
        content="## Details\n\nSome markdown content.", status="idle",
        tags=["Bug", "Backend"],
        created_at=datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return CardData(**defaults)


# ── Serialize / Deserialize ──

def test_roundtrip(tmp_project):
    card = _make_card()
    fpath = card_file_path(str(tmp_project), 42)
    write_card(fpath, card)
    loaded = read_card(fpath)

    assert loaded.id == 42
    assert loaded.list_id == 5
    assert loaded.title == "Fix SQLite pool"
    assert loaded.description == "Serious bug"
    assert loaded.content == "## Details\n\nSome markdown content."
    assert loaded.status == "idle"
    assert loaded.tags == ["Bug", "Backend"]


def test_card_file_path(tmp_project):
    fpath = card_file_path(str(tmp_project), 42)
    assert fpath == tmp_project / ".aegis" / "cards" / "card-000042.md"


def test_empty_content(tmp_project):
    card = _make_card(id=1, content="", description=None, tags=[])
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    loaded = read_card(fpath)
    assert loaded.content == ""
    assert loaded.description is None


def test_atomic_write_no_partial(tmp_project):
    card = _make_card(id=1)
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    assert not fpath.with_suffix(".md.tmp").exists()
    assert fpath.exists()


# ── Validation ──

def test_validate_valid():
    assert validate_frontmatter({"id": 1, "list_id": 1, "title": "X", "status": "idle"}) == []


def test_validate_missing_id():
    errors = validate_frontmatter({"list_id": 1, "title": "X", "status": "idle"})
    assert any("id" in e for e in errors)


def test_validate_bad_status():
    errors = validate_frontmatter({"id": 1, "list_id": 1, "title": "X", "status": "bogus"})
    assert any("status" in e for e in errors)


def test_all_statuses_valid():
    for s in VALID_STATUSES:
        assert validate_frontmatter({"id": 1, "list_id": 1, "title": "X", "status": s}) == []


# ── Edge cases ──

def test_special_chars_in_title(tmp_project):
    card = _make_card(id=2, title='Fix "colon: issue" & <angle>', description="desc: with colon", tags=["tag: special"])
    fpath = card_file_path(str(tmp_project), 2)
    write_card(fpath, card)
    loaded = read_card(fpath)
    assert loaded.title == card.title
    assert loaded.description == card.description
    assert loaded.tags == card.tags


def test_multiline_content(tmp_project):
    content = "# Heading\n\n## Sub\n\n- item 1\n- item 2\n\n```python\nprint('hello')\n```\n"
    card = _make_card(id=3, content=content)
    fpath = card_file_path(str(tmp_project), 3)
    write_card(fpath, card)
    loaded = read_card(fpath)
    # python-frontmatter strips trailing newline from content
    assert loaded.content == content.rstrip("\n")
