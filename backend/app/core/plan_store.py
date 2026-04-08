"""File-based storage for execution plans.

Plans are stored as versioned Markdown files under
`.aegis/plans/{card_id}/round-{n}.md`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.paths import PLANS_DIR

logger = logging.getLogger(__name__)

_ROUND_RE = re.compile(r"^round-(\d+)\.md$")


@dataclass(frozen=True)
class PlanEntry:
    """Immutable descriptor for a stored plan version."""

    card_id: int
    round_num: int
    path: Path


def _card_dir(card_id: int, *, base: Path = PLANS_DIR) -> Path:
    return base / str(card_id)


def save_plan(
    card_id: int,
    round_num: int,
    plan_text: str,
    *,
    base: Path = PLANS_DIR,
) -> Path:
    """Write *plan_text* to ``{base}/{card_id}/round-{round_num}.md``."""
    directory = _card_dir(card_id, base=base)
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / f"round-{round_num}.md"
    file_path.write_text(plan_text, encoding="utf-8")
    logger.info("Saved plan card=%s round=%s -> %s", card_id, round_num, file_path)
    return file_path


def load_plan(
    card_id: int,
    round_num: int,
    *,
    base: Path = PLANS_DIR,
) -> str | None:
    """Return the plan text, or *None* if the file does not exist."""
    file_path = _card_dir(card_id, base=base) / f"round-{round_num}.md"
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")


def list_plans(
    card_id: int,
    *,
    base: Path = PLANS_DIR,
) -> list[PlanEntry]:
    """Return all plan versions for *card_id*, sorted by round number."""
    directory = _card_dir(card_id, base=base)
    if not directory.is_dir():
        return []

    entries: list[PlanEntry] = []
    for child in directory.iterdir():
        m = _ROUND_RE.match(child.name)
        if m:
            entries.append(
                PlanEntry(card_id=card_id, round_num=int(m.group(1)), path=child)
            )

    return sorted(entries, key=lambda e: e.round_num)
