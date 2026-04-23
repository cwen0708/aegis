"""EvolutionStore — 卡片失敗教訓的時間衰減查詢（P2-SH-17 step 1）。

參考研究檔 `self-healing-autoresearch-metaclaw.md:353-377` 與 vendor
`evolution.py:322-414`，但以 Aegis 風格重寫：

- ``LessonEntry`` 為 ``dataclass(frozen=True)``，全程 immutable
- ``EvolutionStore`` 以 ``storage_path`` 注入，不維護 global state
- JSONL 僅以 append 方式寫入，load_all 時逐行解析
- 本 step 不含 prompt overlay 產生與 Executor 整合（留給 step 2）

對應卡片 P2-SH-17。
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


HALF_LIFE_DAYS = 30.0
MAX_AGE_DAYS = 90.0
STAGE_HIT_BOOST = 2.0
SEVERITY_ERROR_BOOST = 1.5


@dataclass(frozen=True)
class LessonEntry:
    """單筆失敗教訓（immutable）。

    ``timestamp_iso`` 使用 ISO 8601 UTC 格式，例如 ``2026-04-23T10:00:00+00:00``；
    支援 ``Z`` 後綴（交由 ``datetime.fromisoformat`` 處理）。
    """
    stage: str
    severity: str
    content: str
    timestamp_iso: str


# ---------------------------------------------------------------------------
# 純函式
# ---------------------------------------------------------------------------


def _parse_iso(timestamp_iso: str) -> datetime:
    """將 ISO 字串解析為 aware UTC datetime。

    若字串無時區資訊則視為 UTC；若帶 ``Z`` 後綴則替換為 ``+00:00``。
    """
    normalized = timestamp_iso.replace("Z", "+00:00") if timestamp_iso.endswith("Z") else timestamp_iso
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def time_weight(timestamp_iso: str, now: datetime | None = None) -> float:
    """依 half-life 計算時間衰減權重。

    - age > ``MAX_AGE_DAYS`` 一律視為過期，回傳 ``0.0``
    - 其他：``exp(-age_days * ln(2) / HALF_LIFE_DAYS)``
    - age < 0（timestamp 在未來）等同 age = 0，權重為 1.0
    """
    reference = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    ts = _parse_iso(timestamp_iso)
    age_days = (reference - ts).total_seconds() / 86400.0
    if age_days > MAX_AGE_DAYS:
        return 0.0
    if age_days < 0:
        age_days = 0.0
    return math.exp(-age_days * math.log(2) / HALF_LIFE_DAYS)


def _score(
    entry: LessonEntry,
    stage_name: str,
    now: datetime | None,
) -> float:
    weight = time_weight(entry.timestamp_iso, now=now)
    if weight <= 0.0:
        return 0.0
    stage_boost = STAGE_HIT_BOOST if entry.stage == stage_name else 1.0
    severity_boost = SEVERITY_ERROR_BOOST if entry.severity == "error" else 1.0
    return weight * stage_boost * severity_boost


# ---------------------------------------------------------------------------
# EvolutionStore（storage_path 注入，無 global state）
# ---------------------------------------------------------------------------


class EvolutionStore:
    """卡片失敗教訓的 JSONL 儲存與時間衰減查詢。

    本 step 只提供 append / load / query 三種能力，不處理 overlay 產生。
    """

    def __init__(self, storage_path: Path) -> None:
        self._path = Path(storage_path)

    @property
    def storage_path(self) -> Path:
        return self._path

    def append_many(self, lessons: list[LessonEntry]) -> None:
        """把 lessons 以 JSONL 形式追加到儲存檔（每行一筆）。"""
        if not lessons:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fp:
            for entry in lessons:
                fp.write(json.dumps(asdict(entry), ensure_ascii=False))
                fp.write("\n")

    def load_all(self) -> list[LessonEntry]:
        """讀取 JSONL 還原所有 entries；檔案不存在回傳空 list。"""
        if not self._path.exists():
            return []
        entries: list[LessonEntry] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                data = json.loads(line)
                entries.append(
                    LessonEntry(
                        stage=data["stage"],
                        severity=data["severity"],
                        content=data["content"],
                        timestamp_iso=data["timestamp_iso"],
                    )
                )
        return entries

    def query_for_stage(
        self,
        stage_name: str,
        max_lessons: int = 5,
        now: datetime | None = None,
    ) -> list[LessonEntry]:
        """按時間衰減與 stage/severity boost 排序後，回傳前 ``max_lessons`` 筆。

        - 過濾 ``score <= 0`` 的 entries（含過期的）
        - 排序穩定：相同 score 時保留原插入順序
        """
        if max_lessons <= 0:
            return []
        scored: list[tuple[float, int, LessonEntry]] = []
        for index, entry in enumerate(self.load_all()):
            score = _score(entry, stage_name=stage_name, now=now)
            if score <= 0.0:
                continue
            scored.append((score, index, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _, _, entry in scored[:max_lessons]]
