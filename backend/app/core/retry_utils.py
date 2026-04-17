"""
Retry Utilities — Jittered backoff & SQLite WAL 專用抖動

參考：hermes-agent self-healing-retry-failover §3.1 / §5
重點：
1. jittered_backoff：指數退避 + 均勻抖動，解 thundering-herd / convoy
2. sqlite_wal_jitter：短距抖動（20-150ms），專治 SQLite WAL busy
3. retry_with_jitter：decorator，失敗即重試，最後一次 raise

seed 公式：time.time_ns() XOR (tick * 0x9E3779B9)
  - 0x9E3779B9 為 golden ratio hash 常數
  - tick 由 _jitter_counter 遞增（threading.Lock 保護）
  - 避免同微秒並發產生相同 seed
"""
from __future__ import annotations

import functools
import random
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_GOLDEN_RATIO_HASH = 0x9E3779B9
_jitter_counter: int = 0
_counter_lock = threading.Lock()


def _next_seed() -> int:
    """取下一個抖動 seed：time_ns() XOR (tick * golden ratio)"""
    global _jitter_counter
    with _counter_lock:
        _jitter_counter += 1
        tick = _jitter_counter
    return time.time_ns() ^ (tick * _GOLDEN_RATIO_HASH)


def jittered_backoff(
    attempt: int,
    base: float = 1.0,
    cap: float = 3600.0,
    jitter: float = 0.25,
) -> float:
    """
    指數退避 + 均勻抖動。

    Args:
        attempt: 第幾次重試（從 0 起算）
        base: 基礎延遲秒數
        cap: 上限秒數，防止指數爆炸
        jitter: 抖動比例（相對於 delay）

    Returns:
        延遲秒數（含抖動），落在 [delay, delay * (1 + jitter)]
    """
    if attempt < 0:
        attempt = 0
    # 2**attempt 可能非常大，先乘 base 再 clamp
    try:
        raw = base * (2 ** attempt)
    except OverflowError:
        raw = cap
    delay = min(cap, raw)
    rng = random.Random(_next_seed())
    return delay + rng.uniform(0.0, jitter * delay)


def sqlite_wal_jitter() -> float:
    """
    SQLite WAL 衝突專用抖動：20-150ms 均勻分佈。

    不與主 backoff 混用——WAL 衝突需要的是短距、密集的重試。
    """
    rng = random.Random(_next_seed())
    return rng.uniform(0.020, 0.150)


def retry_with_jitter(
    max_attempts: int = 5,
    base: float = 1.0,
    cap: float = 3600.0,
    jitter: float = 0.25,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    重試 decorator：失敗時 jittered_backoff sleep，用盡 raise 最後一次 error。

    Args:
        max_attempts: 最多嘗試次數（含第一次）
        base, cap, jitter: 轉給 jittered_backoff

    Example:
        @retry_with_jitter(max_attempts=3)
        def fetch(): ...
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt + 1 >= max_attempts:
                        break
                    time.sleep(jittered_backoff(attempt, base, cap, jitter))
            assert last_error is not None
            raise last_error
        return wrapper
    return decorator
