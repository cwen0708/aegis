"""P2-SH-17 step 1 · EvolutionStore 純資料結構 + 時間衰減查詢。

純資料結構與時間衰減權重測試；本步驟不涉及 Executor 整合、prompt overlay。
所有測試用固定 ``now`` 避免時間敏感；JSONL 檔案以 ``tmp_path`` 隔離。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.evolution_store import (
    HALF_LIFE_DAYS,
    MAX_AGE_DAYS,
    EvolutionStore,
    LessonEntry,
    time_weight,
)


FIXED_NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _iso(offset_days: float) -> str:
    """回傳相對 FIXED_NOW 的 ISO 時間字串（負值代表過去）。"""
    return (FIXED_NOW + timedelta(days=offset_days)).isoformat()


# ---------------------------------------------------------------------------
# time_weight
# ---------------------------------------------------------------------------


class TestTimeWeight:
    def test_time_weight_at_zero_age(self):
        weight = time_weight(_iso(0.0), now=FIXED_NOW)
        assert weight == pytest.approx(1.0, abs=1e-6)

    def test_time_weight_at_half_life(self):
        weight = time_weight(_iso(-HALF_LIFE_DAYS), now=FIXED_NOW)
        assert weight == pytest.approx(0.5, abs=1e-6)

    def test_time_weight_beyond_max_age(self):
        weight = time_weight(_iso(-(MAX_AGE_DAYS + 1)), now=FIXED_NOW)
        assert weight == 0.0


# ---------------------------------------------------------------------------
# append_many / load_all
# ---------------------------------------------------------------------------


class TestAppendAndLoad:
    def test_append_many_creates_jsonl(self, tmp_path):
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        lessons = [
            LessonEntry(
                stage="executor_run",
                severity="error",
                content="boom",
                timestamp_iso=_iso(0.0),
            ),
        ]
        store.append_many(lessons)

        assert store.storage_path.exists()
        loaded = store.load_all()
        assert loaded == lessons

    def test_append_many_appends_not_overwrites(self, tmp_path):
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        first = [
            LessonEntry(
                stage="executor_run",
                severity="error",
                content="first",
                timestamp_iso=_iso(-1.0),
            ),
        ]
        second = [
            LessonEntry(
                stage="review",
                severity="warn",
                content="second",
                timestamp_iso=_iso(0.0),
            ),
        ]
        store.append_many(first)
        store.append_many(second)

        loaded = store.load_all()
        assert loaded == first + second

    def test_load_all_on_missing_file_returns_empty(self, tmp_path):
        store = EvolutionStore(tmp_path / "nope.jsonl")
        assert store.load_all() == []


# ---------------------------------------------------------------------------
# query_for_stage
# ---------------------------------------------------------------------------


class TestQueryForStage:
    def test_query_for_stage_applies_stage_boost(self, tmp_path):
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        hit = LessonEntry(
            stage="executor_run",
            severity="warn",
            content="hit",
            timestamp_iso=_iso(0.0),
        )
        miss = LessonEntry(
            stage="review",
            severity="warn",
            content="miss",
            timestamp_iso=_iso(0.0),
        )
        # 刻意把 miss 放前面，確保排序不是靠插入順序
        store.append_many([miss, hit])

        result = store.query_for_stage("executor_run", max_lessons=5, now=FIXED_NOW)
        assert [e.content for e in result] == ["hit", "miss"]

    def test_query_for_stage_respects_max_lessons(self, tmp_path):
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        lessons = [
            LessonEntry(
                stage="executor_run",
                severity="info",
                content=f"lesson-{i}",
                timestamp_iso=_iso(-i * 0.1),
            )
            for i in range(10)
        ]
        store.append_many(lessons)

        result = store.query_for_stage("executor_run", max_lessons=3, now=FIXED_NOW)
        assert len(result) == 3

    def test_query_for_stage_filters_expired(self, tmp_path):
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        fresh = LessonEntry(
            stage="executor_run",
            severity="info",
            content="fresh",
            timestamp_iso=_iso(-1.0),
        )
        expired = LessonEntry(
            stage="executor_run",
            severity="info",
            content="expired",
            timestamp_iso=_iso(-(MAX_AGE_DAYS + 1)),
        )
        store.append_many([fresh, expired])

        result = store.query_for_stage("executor_run", max_lessons=5, now=FIXED_NOW)
        assert [e.content for e in result] == ["fresh"]

    def test_query_for_stage_error_severity_boost(self, tmp_path):
        """同時間、同 stage 下，severity=error 應比 warn 分數高。"""
        store = EvolutionStore(tmp_path / "lessons.jsonl")
        error_entry = LessonEntry(
            stage="executor_run",
            severity="error",
            content="error-one",
            timestamp_iso=_iso(0.0),
        )
        warn_entry = LessonEntry(
            stage="executor_run",
            severity="warn",
            content="warn-one",
            timestamp_iso=_iso(0.0),
        )
        store.append_many([warn_entry, error_entry])

        result = store.query_for_stage("executor_run", max_lessons=5, now=FIXED_NOW)
        assert [e.content for e in result] == ["error-one", "warn-one"]
