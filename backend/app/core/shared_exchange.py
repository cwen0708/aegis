"""Shared file exchange between AI members.

Members write JSON files to a shared directory so they can exchange data
without burning conversation tokens.  Each file carries a TTL; expired
files are ignored on read and removed by the periodic cleanup.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.paths import EXCHANGE_DIR

logger = logging.getLogger(__name__)


class SharedExchangeManager:
    """Manage read / write / list / cleanup of exchange files."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base = base_dir or EXCHANGE_DIR

    # ── helpers ──────────────────────────────────────────────

    def _member_dir(self, member_slug: str) -> Path:
        d = self._base / member_slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _file_path(self, member_slug: str, key: str) -> Path:
        return self._member_dir(member_slug) / f"{key}.json"

    # ── public API ───────────────────────────────────────────

    def write_exchange(
        self,
        member_slug: str,
        key: str,
        data: dict,
        ttl_seconds: int = 3600,
    ) -> Path:
        """Write *data* as a new exchange file (atomic: tmp -> rename).

        Returns the final Path of the written file.
        """
        now = datetime.now(timezone.utc)
        payload = {
            "metadata": {
                "member_slug": member_slug,
                "created_at": now.isoformat(),
                "ttl_seconds": ttl_seconds,
            },
            "data": data,
        }

        dest = self._file_path(member_slug, key)
        parent = dest.parent
        parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to a temp file in the same directory, then rename.
        fd, tmp_path = tempfile.mkstemp(
            dir=str(parent), suffix=".tmp", prefix=f".{key}_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            # On Windows os.rename fails if dest exists, so remove first.
            if dest.exists():
                dest.unlink()
            os.rename(tmp_path, str(dest))
        except BaseException:
            # Clean up the temp file on failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info("Exchange written: %s", dest)
        return dest

    def read_exchange(self, member_slug: str, key: str) -> Optional[dict]:
        """Read an exchange file.  Returns ``None`` when missing or expired."""
        fpath = self._file_path(member_slug, key)
        if not fpath.exists():
            return None

        try:
            payload = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read exchange %s: %s", fpath, exc)
            return None

        meta = payload.get("metadata", {})
        created_at = datetime.fromisoformat(meta["created_at"])
        ttl = meta.get("ttl_seconds", 3600)

        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
        if elapsed > ttl:
            return None

        return payload.get("data")

    def list_exchanges(
        self, member_slug: Optional[str] = None
    ) -> list[dict]:
        """List available exchange files.

        If *member_slug* is given, only that member's files are returned.
        Each entry contains: key, member_slug, created_at, ttl_seconds, expired.
        """
        results: list[dict] = []
        now = datetime.now(timezone.utc)

        if member_slug:
            slugs = [member_slug]
        else:
            if not self._base.exists():
                return results
            slugs = [
                d.name for d in sorted(self._base.iterdir()) if d.is_dir()
            ]

        for slug in slugs:
            member_dir = self._base / slug
            if not member_dir.exists():
                continue
            for fpath in sorted(member_dir.glob("*.json")):
                try:
                    payload = json.loads(fpath.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                meta = payload.get("metadata", {})
                created_at_str = meta.get("created_at", "")
                ttl = meta.get("ttl_seconds", 3600)
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    expired = (now - created_at).total_seconds() > ttl
                except (ValueError, TypeError):
                    expired = True
                results.append({
                    "key": fpath.stem,
                    "member_slug": slug,
                    "created_at": created_at_str,
                    "ttl_seconds": ttl,
                    "expired": expired,
                })

        return results

    def cleanup_expired(self) -> int:
        """Delete all expired exchange files.  Returns the count deleted."""
        now = datetime.now(timezone.utc)
        deleted = 0

        if not self._base.exists():
            return deleted

        for member_dir in self._base.iterdir():
            if not member_dir.is_dir():
                continue
            for fpath in member_dir.glob("*.json"):
                try:
                    payload = json.loads(fpath.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                meta = payload.get("metadata", {})
                try:
                    created_at = datetime.fromisoformat(meta["created_at"])
                    ttl = meta.get("ttl_seconds", 3600)
                except (KeyError, ValueError, TypeError):
                    continue
                if (now - created_at).total_seconds() > ttl:
                    try:
                        fpath.unlink()
                        deleted += 1
                        logger.info("Expired exchange deleted: %s", fpath)
                    except OSError as exc:
                        logger.warning("Failed to delete %s: %s", fpath, exc)

        return deleted
