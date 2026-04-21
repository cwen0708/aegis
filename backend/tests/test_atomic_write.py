"""Tests for app.core.atomic_write."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import atomic_write


def test_atomic_write_text_basic(tmp_path: Path) -> None:
    dest = tmp_path / "hello.txt"
    atomic_write.atomic_write_text(dest, "你好，小茵")
    assert dest.read_text(encoding="utf-8") == "你好，小茵"


def test_atomic_write_text_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "note.txt"
    dest.write_text("old", encoding="utf-8")
    atomic_write.atomic_write_text(dest, "new")
    assert dest.read_text(encoding="utf-8") == "new"


def test_atomic_write_bytes_basic(tmp_path: Path) -> None:
    dest = tmp_path / "blob.bin"
    payload = b"\x00\x01\x02hello"
    atomic_write.atomic_write_bytes(dest, payload)
    assert dest.read_bytes() == payload


def test_atomic_write_cleanup_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "will_fail.txt"

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_write.os, "replace", boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write.atomic_write_text(dest, "data")

    # Destination not created
    assert not dest.exists()
    # No tmp residue in the target directory
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == [], f"tmp files leaked: {leftovers}"


def test_atomic_write_same_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "sub" / "target.txt"
    dest.parent.mkdir()

    observed: dict[str, str] = {}
    real_mkstemp = atomic_write.tempfile.mkstemp

    def spy_mkstemp(*args, **kwargs):
        observed["dir"] = kwargs.get("dir")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(atomic_write.tempfile, "mkstemp", spy_mkstemp)
    atomic_write.atomic_write_text(dest, "x")

    assert observed["dir"] == str(dest.parent)
    # No tmp files linger after success
    assert list(dest.parent.glob(".*.tmp")) == []
