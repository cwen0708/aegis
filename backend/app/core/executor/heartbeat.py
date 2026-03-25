"""
Heartbeat Monitor — 共用心跳 context manager

使用方式（Worker）：
    with heartbeat_monitor(emitter, card_id=card_id) as touch:
        for line in pty_output:
            touch()
            emitter.emit_raw(line)
"""
import threading
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def heartbeat_monitor(
    emitter,
    idle_threshold: int = 20,
    check_interval: int = 5,
):
    """背景線程每 check_interval 秒檢查，idle 超過 idle_threshold 就 emit_heartbeat。

    abort 檢查由呼叫端的主迴圈負責（heartbeat 線程無法殺進程，放這裡是死碼）。

    Yields:
        touch() — 呼叫方每收到一行輸出就 touch() 重置 idle 計時器
    """
    stop = threading.Event()
    last_activity = [time.time()]

    def _worker():
        while not stop.wait(check_interval):
            idle = time.time() - last_activity[0]
            if idle >= idle_threshold:
                try:
                    emitter.emit_heartbeat(int(idle))
                except Exception:
                    pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    def touch():
        last_activity[0] = time.time()

    try:
        yield touch
    finally:
        stop.set()
        t.join(timeout=2)
