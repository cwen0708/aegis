"""
Tests for backend/app/core/executor/exit_reason.py

對齊 #13090 P0-SH-04 step 1。純函式單測，8 個 AC case 對應卡片需求。
"""
from app.core.executor.exit_reason import ExitReason, classify_exit_reason


def test_normal():
    assert classify_exit_reason("completed", 0) == ExitReason.normal


def test_crashed():
    assert classify_exit_reason("failed", 1) == ExitReason.crashed


def test_killed_negative():
    assert classify_exit_reason("failed", -9) == ExitReason.killed


def test_killed_137():
    assert classify_exit_reason("failed", 137) == ExitReason.killed


def test_truncated():
    assert classify_exit_reason("completed", 0, truncated=True) == ExitReason.truncated


def test_quarantined():
    assert classify_exit_reason("failed", 1, quarantined=True) == ExitReason.quarantined


def test_user_cancelled():
    # user_cancelled 旗標優先於 exit_code=-15 推斷的 killed
    assert (
        classify_exit_reason("failed", -15, user_cancelled=True)
        == ExitReason.user_cancelled
    )


def test_priority_order():
    # 各 flag 同時為 True 時，user_cancelled > quarantined > truncated
    assert (
        classify_exit_reason(
            "failed",
            -9,
            truncated=True,
            quarantined=True,
            user_cancelled=True,
        )
        == ExitReason.user_cancelled
    )
    assert (
        classify_exit_reason(
            "failed",
            -9,
            truncated=True,
            quarantined=True,
            user_cancelled=False,
        )
        == ExitReason.quarantined
    )
    assert (
        classify_exit_reason(
            "failed",
            -9,
            truncated=True,
            quarantined=False,
            user_cancelled=False,
        )
        == ExitReason.truncated
    )
