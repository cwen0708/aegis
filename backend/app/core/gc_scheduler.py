"""
GC Scheduler — 將 gc_scanner 掃描結果去重後自動建卡到 Backlog

流程：
1. 查詢專案的 Backlog list_id
2. 執行 run_gc_scan 取得技術債 findings
3. 比對現有 gc-scan 卡片，用 file + rule_id 去重
4. 對新發現建立 idle 狀態的 Backlog 卡片
"""
import json
import logging

from sqlmodel import Session, select

from app.core.card_factory import create_card
from app.core.card_file import CardData
from app.core.gc_scanner import run_gc_scan
from app.database import engine
from app.models.core import CardIndex, StageList

logger = logging.getLogger(__name__)


def _build_dedup_key(rule_id: str, file: str) -> str:
    """組合 rule_id 與 file 為去重鍵。"""
    return f"{rule_id}:{file}"


def _extract_dedup_key_from_title(title: str) -> str | None:
    """從 gc-scan 卡片標題反解去重鍵。

    標題格式: "chore(gc): {rule_id} — {file} ({message 摘要})"
    """
    prefix = "chore(gc): "
    if not title.startswith(prefix):
        return None
    rest = title[len(prefix):]
    sep_idx = rest.find(" — ")
    if sep_idx < 0:
        return None
    rule_id = rest[:sep_idx]
    after = rest[sep_idx + len(" — "):]
    paren_idx = after.rfind(" (")
    file = after[:paren_idx] if paren_idx >= 0 else after
    return _build_dedup_key(rule_id, file)


def _truncate_message(message: str, max_len: int = 40) -> str:
    """截斷訊息用於標題顯示。"""
    if len(message) <= max_len:
        return message
    return message[: max_len - 1] + "…"


def schedule_gc_scan(project_id: int, project_path: str) -> list[CardData]:
    """掃描專案技術債並為新發現建立 Backlog 卡片。

    Args:
        project_id: 專案 ID
        project_path: 專案根目錄路徑

    Returns:
        本次新建的卡片清單
    """
    with Session(engine) as session:
        # Step 1: 找到 Backlog list
        backlog = session.exec(
            select(StageList).where(
                StageList.project_id == project_id,
                StageList.name == "Backlog",
            )
        ).first()
        if not backlog or backlog.id is None:
            logger.warning(
                "[GCScheduler] No Backlog list for project %d", project_id
            )
            return []

        # Step 2: 執行掃描
        findings = run_gc_scan(project_path)
        if not findings:
            return []

        # Step 3: 查詢現有 gc-scan 卡片做去重
        existing_cards = session.exec(
            select(CardIndex).where(
                CardIndex.project_id == project_id,
                CardIndex.tags_json.contains("gc-scan"),  # type: ignore[union-attr]
            )
        ).all()

        existing_keys: set[str] = set()
        for card in existing_cards:
            key = _extract_dedup_key_from_title(card.title)
            if key:
                existing_keys.add(key)

        # Step 4: 為新發現建卡
        created: list[CardData] = []
        for finding in findings:
            key = _build_dedup_key(finding.rule_id, finding.file)
            if key in existing_keys:
                logger.debug("[GCScheduler] Skip duplicate: %s", key)
                continue

            title = (
                f"chore(gc): {finding.rule_id} — "
                f"{finding.file} ({_truncate_message(finding.message)})"
            )
            card = create_card(
                project_id=project_id,
                list_id=backlog.id,
                title=title,
                content=finding.message,
                status="idle",
                tags=["gc-scan", finding.rule_id],
            )
            if card:
                created.append(card)
                existing_keys.add(key)  # 同批次內也要去重

        logger.info(
            "[GCScheduler] Created %d cards from %d findings",
            len(created),
            len(findings),
        )
        return created
