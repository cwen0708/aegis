"""用量排程器：定期抓取所有帳號的用量並快取，前端只讀快取"""
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = 300  # 每 5 分鐘抓一次（避免 429）

# 快取
_claude_usage_cache: List[Dict[str, Any]] = []
_gemini_usage_cache: Dict[str, Any] = {}
_last_updated: float = 0


def get_cached_claude_usage() -> List[Dict[str, Any]]:
    return _claude_usage_cache


def get_cached_gemini_usage() -> Dict[str, Any]:
    return _gemini_usage_cache


def get_last_updated() -> float:
    return _last_updated


def _fetch_all():
    """同步抓取所有帳號用量（在背景 thread 跑）"""
    global _claude_usage_cache, _gemini_usage_cache, _last_updated

    # Claude
    try:
        from app.core.claude_usage import get_all_accounts_usage
        _claude_usage_cache = get_all_accounts_usage()
        logger.info(f"[UsagePoller] Claude: {len(_claude_usage_cache)} accounts fetched")
    except Exception as e:
        logger.warning(f"[UsagePoller] Claude fetch failed: {e}")

    # Gemini
    try:
        from app.core.gemini_usage import get_gemini_usage
        _gemini_usage_cache = get_gemini_usage()
        logger.info(f"[UsagePoller] Gemini: fetched")
    except Exception as e:
        logger.warning(f"[UsagePoller] Gemini fetch failed: {e}")

    _last_updated = time.time()


async def start_usage_poller():
    """用量輪詢主迴圈"""
    logger.info(f"Starting Usage Poller (interval={POLL_INTERVAL}s)...")

    # 啟動後立即抓一次
    await asyncio.get_event_loop().run_in_executor(None, _fetch_all)

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await asyncio.get_event_loop().run_in_executor(None, _fetch_all)
        except Exception as e:
            logger.error(f"[UsagePoller] Error: {e}")
