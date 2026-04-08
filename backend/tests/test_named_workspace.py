"""Tests for Named Workspace — 命名工作區的 CRUD 與目錄建立。"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import NamedSession
from app.core.named_workspace import (
    create_named_workspace,
    get_named_workspace,
    list_named_workspaces,
)


@pytest.fixture
def db(tmp_path):
    """In-memory SQLite with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """Patch WORKSPACES_ROOT to a temp dir."""
    monkeypatch.setattr("app.core.named_workspace.WORKSPACES_ROOT", tmp_path / "workspaces")
    return tmp_path


# ── Model CRUD ──────────────────────────────────────────


def test_create_named_session(db, ws_root):
    """建立 NamedSession 並驗證欄位正確。"""
    ns = create_named_workspace(db, member_id=1, name="refactor-auth", description="重構認證模組")

    assert ns.id is not None
    assert ns.member_id == 1
    assert ns.name == "refactor-auth"
    assert ns.description == "重構認證模組"
    assert ns.workspace_path != ""


def test_create_with_project_id(db, ws_root):
    """建立時可帶 project_id。"""
    ns = create_named_workspace(db, member_id=1, name="fix-api", project_id=42)
    assert ns.project_id == 42


def test_get_named_workspace(db, ws_root):
    """get_named_workspace 能找到已建立的 session。"""
    create_named_workspace(db, member_id=1, name="my-session")
    found = get_named_workspace(db, member_id=1, name="my-session")
    assert found is not None
    assert found.name == "my-session"


def test_get_named_workspace_not_found(db, ws_root):
    """查無時回傳 None。"""
    result = get_named_workspace(db, member_id=1, name="nonexistent")
    assert result is None


def test_get_named_workspace_wrong_member(db, ws_root):
    """不同 member 查不到彼此的 session。"""
    create_named_workspace(db, member_id=1, name="private")
    result = get_named_workspace(db, member_id=2, name="private")
    assert result is None


def test_list_named_workspaces(db, ws_root):
    """列出指定成員的所有 session。"""
    create_named_workspace(db, member_id=1, name="session-a")
    create_named_workspace(db, member_id=1, name="session-b")
    create_named_workspace(db, member_id=2, name="other")

    results = list_named_workspaces(db, member_id=1)
    assert len(results) == 2
    names = {r.name for r in results}
    assert names == {"session-a", "session-b"}


def test_list_named_workspaces_empty(db, ws_root):
    """無 session 時回傳空 list。"""
    results = list_named_workspaces(db, member_id=99)
    assert results == []


# ── 工作區目錄 ──────────────────────────────────────────


def test_workspace_directory_created(db, ws_root):
    """建立 session 時自動建立 session-{name}/ 目錄。"""
    ns = create_named_workspace(db, member_id=1, name="dev-env")
    ws_dir = ws_root / "workspaces" / "session-dev-env"
    assert ws_dir.exists()
    assert ws_dir.is_dir()
    assert ns.workspace_path == str(ws_dir)


# ── Name 唯一性 ─────────────────────────────────────────


def test_duplicate_name_same_member_raises(db, ws_root):
    """同 member 同名應拋出 IntegrityError。"""
    create_named_workspace(db, member_id=1, name="dup-name")
    with pytest.raises(IntegrityError):
        create_named_workspace(db, member_id=1, name="dup-name")


def test_same_name_different_member_ok(db, ws_root):
    """不同 member 可用相同 name。"""
    ns1 = create_named_workspace(db, member_id=1, name="shared-name")
    ns2 = create_named_workspace(db, member_id=2, name="shared-name")
    assert ns1.id != ns2.id


# ── Name 驗證 ───────────────────────────────────────────


def test_invalid_name_raises():
    """不合法名稱應拋出 ValueError。"""
    from app.core.named_workspace import _validate_name
    with pytest.raises(ValueError):
        _validate_name("")
    with pytest.raises(ValueError):
        _validate_name("-starts-with-dash")
    with pytest.raises(ValueError):
        _validate_name("has space")
    with pytest.raises(ValueError):
        _validate_name("a" * 64)  # 超過 63 字元


def test_valid_names():
    """合法名稱不應拋出。"""
    from app.core.named_workspace import _validate_name
    assert _validate_name("refactor-auth") == "refactor-auth"
    assert _validate_name("session_01") == "session_01"
    assert _validate_name("A") == "A"
    assert _validate_name("a" * 63) == "a" * 63
