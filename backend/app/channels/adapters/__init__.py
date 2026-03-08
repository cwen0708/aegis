"""頻道適配器 — lazy import，缺少依賴時不會中斷啟動"""
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "TelegramChannel",
    "LineChannel",
    "DiscordChannel",
    "SlackChannel",
    "WeComChannel",
    "FeishuChannel",
]


def __getattr__(name: str):
    """Lazy import: 只在真正用到時才載入，缺模組就報錯而非啟動失敗"""
    _map = {
        "TelegramChannel": ".telegram",
        "LineChannel": ".line",
        "DiscordChannel": ".discord",
        "SlackChannel": ".slack",
        "WeComChannel": ".wecom",
        "FeishuChannel": ".feishu",
    }
    if name in _map:
        import importlib
        try:
            mod = importlib.import_module(_map[name], package=__package__)
            return getattr(mod, name)
        except ImportError as e:
            logger.warning(f"Channel adapter {name} unavailable: {e}")
            raise
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
