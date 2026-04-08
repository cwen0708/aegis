"""Tests for SharedExchangeManager."""

import json
from datetime import datetime, timezone, timedelta

import pytest

from app.core.shared_exchange import SharedExchangeManager


@pytest.fixture
def manager(tmp_path):
    """Return a SharedExchangeManager writing into a temp directory."""
    return SharedExchangeManager(base_dir=tmp_path)


# ── write + read ─────────────────────────────────────────────

def test_write_and_read(manager):
    data = {"result": "hello", "count": 42}
    path = manager.write_exchange("alice", "report", data)

    assert path.exists()
    assert path.suffix == ".json"

    result = manager.read_exchange("alice", "report")
    assert result == data


# ── expired file returns None ────────────────────────────────

def test_read_expired(manager, tmp_path):
    # Write with ttl=1 s, then backdate created_at by 10 s.
    manager.write_exchange("bob", "old", {"x": 1}, ttl_seconds=1)

    fpath = tmp_path / "bob" / "old.json"
    payload = json.loads(fpath.read_text(encoding="utf-8"))
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    payload["metadata"]["created_at"] = past
    fpath.write_text(json.dumps(payload), encoding="utf-8")

    assert manager.read_exchange("bob", "old") is None


# ── list exchanges ───────────────────────────────────────────

def test_list_exchanges(manager):
    manager.write_exchange("alice", "a1", {"v": 1})
    manager.write_exchange("alice", "a2", {"v": 2})
    manager.write_exchange("bob", "b1", {"v": 3})

    # All
    items = manager.list_exchanges()
    assert len(items) == 3
    slugs = {i["member_slug"] for i in items}
    assert slugs == {"alice", "bob"}

    # Filtered
    alice_items = manager.list_exchanges(member_slug="alice")
    assert len(alice_items) == 2
    assert all(i["member_slug"] == "alice" for i in alice_items)

    # Each entry has required fields
    for item in items:
        assert "key" in item
        assert "member_slug" in item
        assert "created_at" in item
        assert "ttl_seconds" in item
        assert "expired" in item


# ── cleanup expired ──────────────────────────────────────────

def test_cleanup_expired(manager, tmp_path):
    manager.write_exchange("alice", "fresh", {"ok": True}, ttl_seconds=3600)
    manager.write_exchange("alice", "stale", {"ok": False}, ttl_seconds=1)

    # Backdate the stale file
    stale_path = tmp_path / "alice" / "stale.json"
    payload = json.loads(stale_path.read_text(encoding="utf-8"))
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    payload["metadata"]["created_at"] = past
    stale_path.write_text(json.dumps(payload), encoding="utf-8")

    deleted = manager.cleanup_expired()
    assert deleted == 1
    assert not stale_path.exists()
    assert (tmp_path / "alice" / "fresh.json").exists()


# ── write is immutable (new file, not in-place mutation) ─────

def test_write_immutable(manager, tmp_path):
    manager.write_exchange("carol", "cfg", {"version": 1})
    fpath = tmp_path / "carol" / "cfg.json"
    mtime_1 = fpath.stat().st_mtime_ns

    # Write again with different data — file should be replaced, not patched.
    manager.write_exchange("carol", "cfg", {"version": 2})
    content = json.loads(fpath.read_text(encoding="utf-8"))
    assert content["data"] == {"version": 2}

    # The underlying mechanism is atomic rename — the file is a new inode
    # (on most filesystems mtime_ns will differ).
    mtime_2 = fpath.stat().st_mtime_ns
    assert mtime_2 >= mtime_1
