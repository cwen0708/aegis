#!/usr/bin/env python3
"""一次性腳本：掃描所有成員記憶檔案，批次計算 embedding 並寫入 SQLite。

用法：
    python scripts/backfill_embeddings.py            # 實際執行
    python scripts/backfill_embeddings.py --dry-run   # 只掃描不寫入
    python scripts/backfill_embeddings.py --members-root /path/to/.aegis/members
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 確保 backend/ 在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.embedding import embed_and_store  # noqa: E402
from app.core.member_profile import MEMBERS_ROOT  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.2  # 秒，控制 OpenAI API rate limit


def scan_memory_files(members_root: Path) -> list[tuple[str, Path]]:
    """掃描所有成員的記憶檔案，回傳 (member_slug, file_path) 清單。"""
    results: list[tuple[str, Path]] = []
    if not members_root.exists():
        logger.warning(f"Members root not found: {members_root}")
        return results

    for member_dir in sorted(members_root.iterdir()):
        if not member_dir.is_dir():
            continue
        slug = member_dir.name
        for sub in ("short-term", "long-term"):
            mem_dir = member_dir / "memory" / sub
            if not mem_dir.exists():
                continue
            for md_file in sorted(mem_dir.glob("*.md")):
                results.append((slug, md_file))
    return results


async def backfill(dry_run: bool = False, members_root: Path | None = None) -> dict:
    """執行 backfill，回傳統計結果。"""
    root = members_root or MEMBERS_ROOT
    files = scan_memory_files(root)
    stats = {"total": len(files), "added": 0, "skipped": 0, "failed": 0}

    logger.info(f"掃描到 {stats['total']} 個記憶檔案（root: {root}）")

    if dry_run:
        for slug, fpath in files:
            logger.info(f"  [dry-run] {slug}: {fpath}")
        logger.info(f"Dry-run 完成：共 {stats['total']} 個檔案")
        return stats

    for slug, fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8")
            if not content.strip():
                stats["skipped"] += 1
                continue

            ok = await embed_and_store(
                entity_type="memory",
                entity_key=str(fpath),
                content=content,
                member_slug=slug,
            )
            if ok:
                stats["added"] += 1
                logger.info(f"  ✓ {slug}: {fpath.name}")
            else:
                stats["failed"] += 1
                logger.warning(f"  ✗ {slug}: {fpath.name} (embed failed)")
        except Exception as e:
            stats["failed"] += 1
            logger.error(f"  ✗ {slug}: {fpath.name} — {e}")

        await asyncio.sleep(RATE_LIMIT_DELAY)

    logger.info(
        f"完成：總計 {stats['total']} / 成功 {stats['added']} / "
        f"空檔跳過 {stats['skipped']} / 失敗 {stats['failed']}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill memory embeddings")
    parser.add_argument("--dry-run", action="store_true", help="只掃描不寫入")
    parser.add_argument("--members-root", type=str, default=None, help="成員根目錄路徑（預設使用 MEMBERS_ROOT）")
    args = parser.parse_args()

    root = Path(args.members_root) if args.members_root else None
    asyncio.run(backfill(dry_run=args.dry_run, members_root=root))


if __name__ == "__main__":
    main()
