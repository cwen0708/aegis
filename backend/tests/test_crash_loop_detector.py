"""Tests for crash_loop_detector（P0-SH-03 step 1 純函式骨架）。

覆蓋：不變性、trim 過期、閾值判定（未到/剛到/含過期者）、DEFAULT_WINDOW 常數。
"""
from __future__ import annotations

from app.core.crash_loop_detector import (
    DEFAULT_WINDOW,
    CrashWindow,
    is_crash_loop,
    record_crash,
    trim,
)


def test_record_crash_returns_new_window() -> None:
    """record_crash 應回傳新物件，原 window 的 timestamps 不被修改。"""
    original = CrashWindow(timestamps=(100.0,), duration_s=300.0, max_crashes=3)
    updated = record_crash(original, now=200.0)

    # 新 window 含兩筆
    assert updated.timestamps == (100.0, 200.0)
    # 原 window 未被 mutate
    assert original.timestamps == (100.0,)
    # 是不同物件
    assert updated is not original


def test_trim_removes_old_timestamps() -> None:
    """now=1000, duration=300 時，< 700 的 timestamps 應被過濾。"""
    window = CrashWindow(
        timestamps=(500.0, 650.0, 700.0, 800.0, 950.0),
        duration_s=300.0,
        max_crashes=3,
    )
    trimmed = trim(window, now=1000.0)

    # 保留 >= 700 者，順序維持
    assert trimmed.timestamps == (700.0, 800.0, 950.0)
    # 其他欄位不變
    assert trimmed.duration_s == 300.0
    assert trimmed.max_crashes == 3


def test_is_crash_loop_false_under_threshold() -> None:
    """2 次 crash < max_crashes(3)，不算 crash loop。"""
    window = CrashWindow(
        timestamps=(900.0, 950.0),
        duration_s=300.0,
        max_crashes=3,
    )
    assert is_crash_loop(window, now=1000.0) is False


def test_is_crash_loop_true_at_threshold() -> None:
    """3 次 crash 在 300s 窗口內，達到 max_crashes，判定為 crash loop。"""
    window = CrashWindow(
        timestamps=(800.0, 900.0, 950.0),
        duration_s=300.0,
        max_crashes=3,
    )
    assert is_crash_loop(window, now=1000.0) is True


def test_is_crash_loop_ignores_expired() -> None:
    """5 次 crash 中 3 次在 5 分鐘外 → 有效僅 2 次，不算 crash loop。"""
    # duration=300, now=1000 → threshold=700
    # 400/500/600 過期；800/950 保留
    window = CrashWindow(
        timestamps=(400.0, 500.0, 600.0, 800.0, 950.0),
        duration_s=300.0,
        max_crashes=3,
    )
    assert is_crash_loop(window, now=1000.0) is False


def test_default_window_constants() -> None:
    """DEFAULT_WINDOW 應為空 tuple、300 秒、3 次。"""
    assert DEFAULT_WINDOW.timestamps == ()
    assert DEFAULT_WINDOW.duration_s == 300.0
    assert DEFAULT_WINDOW.max_crashes == 3
