"""
Tests for app.core.retry_utils

AC 對應：
- backoff 有上限（cap）
- backoff 每次呼叫有抖動（非固定值）
- convoy 場景（多並發）方差 > 固定 backoff 的 10 倍
- SQLite WAL 專用抖動落在 [0.020, 0.150]
- retry decorator 成功路徑 & 耗盡 raise
"""
import statistics
import threading
from typing import List
from unittest.mock import patch

import pytest

from app.core.retry_utils import (
    jittered_backoff,
    sqlite_wal_jitter,
    retry_with_jitter,
)


def test_backoff_bounded_by_cap() -> None:
    """AC：attempt 極大時仍應受 cap 限制"""
    for _ in range(20):
        delay = jittered_backoff(attempt=100, base=1.0, cap=60.0, jitter=0.25)
        assert delay <= 60.0 * (1 + 0.25) + 1e-9
        assert delay >= 0.0


def test_backoff_has_jitter() -> None:
    """AC：同 attempt 呼叫多次應產生不同值（有抖動）"""
    samples = [jittered_backoff(attempt=3, base=1.0, cap=3600.0) for _ in range(100)]
    stdev = statistics.pstdev(samples)
    assert stdev > 0.0, "backoff 應該要有抖動"
    # 所有樣本不應完全相同
    assert len(set(samples)) > 1


def test_backoff_convoy_variance() -> None:
    """
    AC 主驗證：100 並發樣本的方差 > 固定 backoff 的 10 倍

    固定 backoff（無抖動）方差 = 0，任何大於 0 的方差即滿足
    但我們要求抖動幅度有意義——方差 > 0.1（attempt=3, base=1, delay≈8）
    """
    results: List[float] = []
    lock = threading.Lock()

    def worker() -> None:
        value = jittered_backoff(attempt=3, base=1.0, cap=3600.0, jitter=0.25)
        with lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 100
    variance = statistics.pvariance(results)
    # 固定 backoff（無抖動）variance = 0；我們要求變異度夠大
    # attempt=3, base=1 → delay≈8, jitter 範圍 [0, 2]，方差應接近 0.3 以上
    assert variance > 0.1, f"convoy variance 太低：{variance}"


def test_backoff_zero_attempt() -> None:
    """attempt=0 應回傳 base 附近的值"""
    delay = jittered_backoff(attempt=0, base=1.0, cap=60.0, jitter=0.0)
    assert delay == pytest.approx(1.0)


def test_sqlite_wal_jitter_range() -> None:
    """AC：SQLite WAL 抖動固定落在 [0.020, 0.150]"""
    for _ in range(200):
        delay = sqlite_wal_jitter()
        assert 0.020 <= delay <= 0.150


def test_retry_with_jitter_success() -> None:
    """AC：第 3 次成功回傳正確結果"""
    call_count = {"n": 0}

    @retry_with_jitter(max_attempts=5, base=0.001, cap=0.01)
    def flaky() -> str:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    with patch("app.core.retry_utils.time.sleep"):  # 加速測試
        result = flaky()

    assert result == "ok"
    assert call_count["n"] == 3


def test_retry_with_jitter_exhausted() -> None:
    """AC：全部失敗時 raise 最後一次 error"""
    call_count = {"n": 0}

    @retry_with_jitter(max_attempts=3, base=0.001, cap=0.01)
    def always_fail() -> None:
        call_count["n"] += 1
        raise ValueError(f"fail-{call_count['n']}")

    with patch("app.core.retry_utils.time.sleep"):
        with pytest.raises(ValueError, match="fail-3"):
            always_fail()

    assert call_count["n"] == 3
