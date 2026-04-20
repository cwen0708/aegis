"""Atomic file write helpers.

Write to a temp file in the target's parent directory, fsync, then
``os.replace`` onto the destination. ``os.replace`` is atomic on POSIX and
Windows, so readers never observe a half-written file.

Keep the tmp file in ``path.parent`` — cross-filesystem rename fails.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _write_and_replace(path: Path, writer) -> None:
    parent = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".", suffix=".tmp")
    try:
        try:
            with os.fdopen(fd, "wb") as fh:
                writer(fh)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            # fdopen took ownership of fd; if its context manager already ran,
            # fd is closed. Fall through to tmp cleanup.
            raise
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path``."""
    _write_and_replace(path, lambda fh: fh.write(data))


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write ``content`` to ``path`` using ``encoding``."""
    atomic_write_bytes(path, content.encode(encoding))
