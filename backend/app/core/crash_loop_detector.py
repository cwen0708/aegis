"""Crash loop detector — 滑動窗口型崩潰迴圈偵測（純函式）。

來源：self-healing-alphaclaw-ironclaw.md §1.5（AlphaClaw `watchdog.js:L157-162, L744-783`）。
用途：判斷某個受監控對象（例如 card / worker）是否在短時間內反覆 crash，
作為 `watchdog.py` 既有 retry count 上限之外的時間窗口型互補保護。

本 step 先提供純函式 API（無 IO、無全域副作用），**尚未接線**到 watchdog.py。
所有資料皆不可變：`CrashWindow` 是 frozen dataclass，timestamps 是 tuple。
後續 step 再做接線、Telegram 去重、card quarantine、/resume endpoint 等 IO 行為。
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CrashWindow:
    """滑動窗口崩潰紀錄。

    Attributes:
        timestamps: 已記錄的 crash 發生時刻（單位：秒；用 tuple 保證不可變）。
        duration_s: 窗口長度（秒）。超過此長度的 timestamps 會被視為過期。
        max_crashes: 達到此次數即判定為 crash loop。
    """

    timestamps: tuple[float, ...]
    duration_s: float
    max_crashes: int


def trim(window: CrashWindow, now: float) -> CrashWindow:
    """回傳移除過期 timestamps 的新 window（不 mutate 原物件）。

    Args:
        window: 當前窗口狀態。
        now: 現在時刻（秒）。timestamps 中 < (now - duration_s) 的視為過期。

    Returns:
        新的 CrashWindow，timestamps 僅保留未過期者（順序不變）。
    """
    threshold = now - window.duration_s
    kept = tuple(ts for ts in window.timestamps if ts >= threshold)
    return replace(window, timestamps=kept)


def record_crash(window: CrashWindow, now: float) -> CrashWindow:
    """回傳新增 now timestamp 後的新 window（不 mutate 原物件）。

    會先 trim 過期紀錄，再 append now，確保 timestamps 不會無限制增長。

    Args:
        window: 當前窗口狀態。
        now: 本次 crash 發生時刻（秒）。

    Returns:
        新的 CrashWindow。
    """
    trimmed = trim(window, now)
    return replace(trimmed, timestamps=trimmed.timestamps + (now,))


def is_crash_loop(window: CrashWindow, now: float) -> bool:
    """判斷是否達到 crash loop 閾值。

    先 trim 過期紀錄後，比較剩餘 timestamps 數量與 max_crashes。

    Args:
        window: 當前窗口狀態。
        now: 現在時刻（秒），用於判定過期。

    Returns:
        True 表示滑動窗口內 crash 次數 ≥ max_crashes。
    """
    trimmed = trim(window, now)
    return len(trimmed.timestamps) >= trimmed.max_crashes


DEFAULT_WINDOW: CrashWindow = CrashWindow(
    timestamps=(),
    duration_s=300.0,
    max_crashes=3,
)
