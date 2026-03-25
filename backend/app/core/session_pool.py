"""Chat Session Pool — chat_id 到 Claude CLI session_id 的映射，帶 TTL 自動過期。

用 --resume 做多輪對話延續。每次仍啟新進程但 cache hit 省 token。

用法：
    from app.core.session_pool import session_pool

    resume_id, is_new = session_pool.get_or_create("telegram:123:xiao-yin")
    session_pool.register("telegram:123:xiao-yin", "abc-def-123")
    session_pool.invalidate("telegram:123:xiao-yin")
"""
import time
import threading
import logging

logger = logging.getLogger(__name__)

SESSION_TTL = 1800  # 30 分鐘


class SessionPool:
    """chat_id → Claude CLI session_id 的映射，帶 TTL 自動過期。"""

    def __init__(self, ttl: int = SESSION_TTL):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get_or_create(self, chat_id: str) -> tuple[str | None, bool]:
        """回傳 (session_id_or_None, is_new)。"""
        with self._lock:
            self._cleanup_expired()
            entry = self._sessions.get(chat_id)
            if entry:
                entry["last_active"] = time.time()
                logger.info(f"[SessionPool] Reusing session {entry['session_id'][:8]}... for {chat_id}")
                return entry["session_id"], False
            return None, True

    def register(self, chat_id: str, session_id: str):
        """對話完成後註冊 session_id。"""
        with self._lock:
            self._sessions[chat_id] = {
                "session_id": session_id,
                "last_active": time.time(),
            }
            logger.info(f"[SessionPool] Registered session {session_id[:8]}... for {chat_id}")

    def invalidate(self, chat_id: str):
        """手動清除。"""
        with self._lock:
            removed = self._sessions.pop(chat_id, None)
            if removed:
                logger.info(f"[SessionPool] Invalidated session for {chat_id}")

    def active_count(self) -> int:
        with self._lock:
            self._cleanup_expired()
            return len(self._sessions)

    def _cleanup_expired(self):
        now = time.time()
        expired = [k for k, v in self._sessions.items()
                   if now - v["last_active"] > self._ttl]
        for k in expired:
            sid = self._sessions[k]["session_id"]
            logger.info(f"[SessionPool] Expired session {sid[:8]}... for {k}")
            del self._sessions[k]


# 全域 singleton
session_pool = SessionPool()
