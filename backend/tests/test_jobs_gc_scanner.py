"""Unit tests for app.jobs.gc_scanner (Step 1 MVP)."""
from __future__ import annotations

from pathlib import Path

from app.jobs.gc_scanner import TechDebtMarker, scan_todo_comments


def test_scan_finds_todo(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def greet():\n"
        "    # TODO: refactor greeting\n"
        "    return 'hi'\n",
        encoding="utf-8",
    )

    markers = scan_todo_comments(tmp_path)

    assert len(markers) == 1
    marker = markers[0]
    assert isinstance(marker, TechDebtMarker)
    assert marker.file_path == str(source)
    assert marker.line_no == 2
    assert marker.kind == "TODO"
    assert "refactor greeting" in marker.content


def test_scan_ignores_venv(tmp_path: Path) -> None:
    vendored = tmp_path / "venv" / "lib" / "fake.py"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("# TODO: ignored vendor marker\n", encoding="utf-8")

    kept = tmp_path / "app.py"
    kept.write_text("# TODO: keep this\n", encoding="utf-8")

    markers = scan_todo_comments(tmp_path)

    assert len(markers) == 1
    assert markers[0].file_path == str(kept)


def test_scan_classifies_kind(tmp_path: Path) -> None:
    source = tmp_path / "debt.py"
    source.write_text(
        "# TODO: one\n"
        "# FIXME: two\n"
        "# XXX: three\n"
        "# HACK: four\n",
        encoding="utf-8",
    )

    markers = scan_todo_comments(tmp_path)

    kinds = [m.kind for m in markers]
    assert kinds == ["TODO", "FIXME", "XXX", "HACK"]
    line_numbers = [m.line_no for m in markers]
    assert line_numbers == sorted(line_numbers)
