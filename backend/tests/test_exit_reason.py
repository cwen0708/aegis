"""
Tests for backend/app/core/executor/exit_reason.py

對齊 #13090 P0-SH-04 step 1 + step 2。純函式單測：
- step 1：8 個 classify_exit_reason AC case。
- step 2：enrich_result_with_exit_reason 將 worker result dict 補上 exit_reason 欄位，
  驗證 worker.py 的 status 語彙（success/error/timeout）映射正確且保持不變性。
"""
from app.core.executor.exit_reason import (
    ExitReason,
    classify_exit_reason,
    enrich_result_with_exit_reason,
)


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


# -----------------------------
# step 2：enrich_result_with_exit_reason
# -----------------------------


def test_enrich_success_normal():
    result = {"status": "success", "output": "ok", "exit_code": 0}
    enriched = enrich_result_with_exit_reason(result)
    assert enriched["exit_reason"] == ExitReason.normal.value
    assert enriched["exit_reason"] == "normal"


def test_enrich_error_crashed():
    result = {"status": "error", "output": "boom", "exit_code": 1}
    enriched = enrich_result_with_exit_reason(result)
    assert enriched["exit_reason"] == "crashed"


def test_enrich_error_sigterm_killed():
    result = {"status": "error", "output": "terminated", "exit_code": 143}
    enriched = enrich_result_with_exit_reason(result)
    assert enriched["exit_reason"] == "killed"


def test_enrich_timeout_killed():
    result = {"status": "timeout", "output": "timeout", "exit_code": -1}
    enriched = enrich_result_with_exit_reason(result)
    assert enriched["exit_reason"] == "killed"


def test_enrich_returns_new_dict_immutable():
    result = {"status": "success", "exit_code": 0}
    enriched = enrich_result_with_exit_reason(result)
    # 不變性：回傳全新 dict，原 dict 不被修改
    assert id(enriched) != id(result)
    assert "exit_reason" not in result
    assert enriched["exit_reason"] == "normal"
    # 其他欄位完整保留
    assert enriched["status"] == "success"
    assert enriched["exit_code"] == 0


def test_enrich_missing_exit_code_defaults_to_zero():
    # 防呆：exception 路徑可能沒有 exit_code，應視為 0（由 status 決定）
    result = {"status": "error", "output": "exception"}
    enriched = enrich_result_with_exit_reason(result)
    assert enriched["exit_reason"] == "crashed"
