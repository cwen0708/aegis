"""WatchdogMonitor 核心狀態機 — idle-aware 自動重啟機制。

狀態轉換：IDLE → BUSY → SUSPECTED → RESTART
連續 5 次無心跳觸發 SUSPECTED，加 pre_restart_check 防誤判。
冷卻策略 [60, 120, 240] 秒指數遞增，3 次失敗 fallback 到診斷報告 + alert。

## 任務層級重試 vs 進程層級重啟的區分

### 任務層級重試（Task-Level Retry）
- **負責方**：error_classifier + worker 主迴圈
- **機制**：單個卡片（task）遇到 retryable 錯誤時，由 error classifier 標記，worker 在同一進程內重試
- **計數器**：`card.retry_count`（持久化在 DB），獨立於進程，每個任務獨立計數
- **上限**：MAX_RETRY_ATTEMPTS（預設 3）
- **何時觸發**：任務執行失敗，error_classifier 判定為 retryable
- **例子**：API 超時、暫時性網路錯誤、磁盤滿等

### 進程層級重啟（Process-Level Restart）
- **負責方**：WatchdogMonitor（本模組）
- **機制**：進程對應的 chat_key 無心跳超過閾值時，由 Watchdog 強制終止進程，重新啟動
- **計數器**：`CardWatchdogState.retry_count`（記憶體中，進程重啟時清零），全域 Watchdog 管理
- **上限**：MAX_RETRIES（預設 3）
- **何時觸發**：進程卡死（非 idle 卻無心跳超過 60 秒），pre_restart_check 三階段通過
- **例子**：子進程無限迴圈、死鎖、段錯誤後無輸出等

### 兩者銜接點（Integration Point）
當同一個任務導致進程反覆卡死時（Watchdog 重啟多次）：

1. **第 1 次重啟**：Watchdog 重啟進程（WatchdogState.retry_count = 1）
   - 卡片重新進入 worker 排程（status = "pending"）
   - 卡片的 task-level retry_count 不受影響，仍為之前的值
   - worker 再次執行該卡片

2. **第 2 次重啟**：如果卡片再次卡死
   - Watchdog 再次重啟（WatchdogState.retry_count = 2）
   - 卡片重新入排程，task-level retry_count 仍累積

3. **第 3 次重啟失敗**：Watchdog 耗盡重啟次數（MAX_RETRIES = 3）
   - Watchdog fallback：標記卡片為 failed，記錄診斷報告
   - 卡片此時的 task-level retry_count 也會被紀錄
   - 最終狀態：`card.status = "failed"`，同時記錄了進程重啟和任務重試的歷史

### 設計原則
- **獨立計數**：task retry_count 和 watchdog restart retry_count 分別追蹤
- **累積記錄**：Watchdog 重啟後，task 重試計數繼續累積，直到達到上限後標記失敗
- **清晰邊界**：
  - Task 在 pending/running/failed 狀態間轉換（持久化）
  - Watchdog 在 IDLE/BUSY/SUSPECTED/RESTART 狀態間轉換（記憶體）
  - 兩套系統各自独立但協調：task 失敗時 Watchdog 回到 IDLE，Watchdog 重啟時 task 回到 pending
"""
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Tuple, Any

logger = logging.getLogger(__name__)

# ── 心跳超時閾值 ──────────────────────────────────────────
# 超過此秒數無心跳，視為進程可能卡死
WATCHDOG_HEARTBEAT_TIMEOUT: int = 60   # 秒；Stage 1 / Stage 3 閾值

# 在 Stage 1 超時後的額外寬限期（處理 npm install 等長時操作）
WATCHDOG_GRACE_PERIOD: int = 30        # 秒；Stage 2 額外寬限 = 60 + 30 = 90s

# 連續幾次無心跳才進入 SUSPECTED
HEARTBEAT_CHECK_COUNT: int = 5

# 心跳檢查間隔（秒）
HEARTBEAT_CHECK_INTERVAL: int = 12

# 重啟冷卻策略（指數遞增，秒）
RESTART_COOLDOWNS: tuple = (60, 120, 240)

# 最大重啟次數，超過後 fallback 到診斷報告
MAX_RETRIES: int = 3

# process pool 進程存活檢查 timeout（秒）
PROCESS_ALIVE_CHECK_TIMEOUT: int = 2

# 任務隊列檢查 timeout（秒）
TASK_QUEUE_CHECK_TIMEOUT: int = 1


class WatchdogState(str, Enum):
    """Watchdog 狀態機的四個狀態。"""
    IDLE = "idle"
    BUSY = "busy"
    SUSPECTED = "suspected"
    RESTART = "restart"


@dataclass
class CardWatchdogState:
    """單張卡片的 Watchdog 狀態追蹤。"""
    card_id: int
    state: WatchdogState = WatchdogState.BUSY
    last_heartbeat_time: Optional[float] = None
    no_heartbeat_count: int = 0
    retry_count: int = 0
    cooldown_until: float = 0.0
    entered_suspected_at: Optional[float] = None


@dataclass
class WatchdogMonitorState:
    """全局 Watchdog 監控狀態。"""
    card_states: dict = field(default_factory=dict)
    total_checks: int = 0
    total_suspected: int = 0
    total_restarts: int = 0
    total_fallbacks: int = 0

    def reset(self):
        """Reset 所有狀態（Worker 啟動時調用）。"""
        self.card_states = {}
        self.total_checks = 0
        self.total_suspected = 0
        self.total_restarts = 0
        self.total_fallbacks = 0


class WatchdogMonitor:
    """Watchdog 核心狀態機 — 檢查進程心跳，執行自動重啟。

    工作流程：
    1. 監控卡片狀態（IDLE/BUSY/SUSPECTED/RESTART）
    2. 檢查心跳活動，累計無心跳次數
    3. 執行 pre_restart_check 防誤判
    4. 管理冷卻策略與重試計數
    5. Fallback 到診斷報告與告警
    """

    def __init__(
        self,
        get_idle_status_fn: Callable,
        get_heartbeat_fn: Callable,
        process_pool: Any = None,
    ):
        """初始化 Watchdog。

        Args:
            get_idle_status_fn: 取得系統閒置狀態的回調函數
                簽名：(card_id: int) -> (is_idle: bool, busy_reasons: list[str])
            get_heartbeat_fn: 取得卡片最後心跳時間的回調函數
                簽名：(card_id: int) -> Optional[float]（Unix timestamp）
            process_pool: 可選的 ProcessPool 實例，用於 Stage 3 的進程隊列檢查
                若提供，Stage 3 會調用 process_pool.has_active_process(card_id)
        """
        self.state = WatchdogMonitorState()
        self.get_idle_status_fn = get_idle_status_fn
        self.get_heartbeat_fn = get_heartbeat_fn
        self.process_pool = process_pool

    def check_card(self, card_id: int, is_running: bool) -> Tuple[WatchdogState, dict]:
        """檢查單張卡片的狀態，執行狀態轉換邏輯。

        Args:
            card_id: 卡片 ID
            is_running: 卡片是否處於 running 狀態

        Returns:
            (new_state, metadata) 其中 metadata 包含：
                - old_state: 舊狀態
                - state_changed: 是否狀態轉換
                - reason: 轉換原因
                - should_restart: 是否應該重啟
                - cooldown_active: 是否冷卻中
        """
        self.state.total_checks += 1

        # 初始化卡片狀態
        if card_id not in self.state.card_states:
            self.state.card_states[card_id] = CardWatchdogState(card_id=card_id)

        card_state = self.state.card_states[card_id]
        old_state = card_state.state
        now = time.time()

        # 冷卻中：不執行重啟，等待冷卻結束
        if card_state.cooldown_until > now:
            return (
                WatchdogState.IDLE,
                {
                    "old_state": old_state.value,
                    "state_changed": False,
                    "reason": "cooldown_active",
                    "should_restart": False,
                    "cooldown_active": True,
                    "cooldown_remaining": card_state.cooldown_until - now,
                    "no_heartbeat_count": card_state.no_heartbeat_count,
                },
            )

        # 取得系統閒置狀態
        is_idle, busy_reasons = self.get_idle_status_fn(card_id)

        if is_idle:
            new_state = WatchdogState.IDLE
            card_state.state = new_state
            card_state.no_heartbeat_count = 0
            card_state.last_heartbeat_time = None
            card_state.entered_suspected_at = None
            return (
                new_state,
                {
                    "old_state": old_state.value,
                    "state_changed": old_state != new_state,
                    "reason": "system_idle",
                    "should_restart": False,
                    "cooldown_active": False,
                    "no_heartbeat_count": 0,
                },
            )

        # 取得心跳時間
        last_hb = self.get_heartbeat_fn(card_id)
        is_heartbeat_alive = last_hb and (now - last_hb) < WATCHDOG_HEARTBEAT_TIMEOUT

        if is_heartbeat_alive:
            new_state = WatchdogState.BUSY
            if card_state.state != WatchdogState.BUSY:
                card_state.no_heartbeat_count = 0
            card_state.last_heartbeat_time = last_hb
            card_state.state = new_state
            return (
                new_state,
                {
                    "old_state": old_state.value,
                    "state_changed": old_state != new_state,
                    "reason": f"heartbeat_alive ({now - last_hb:.0f}s ago)",
                    "should_restart": False,
                    "cooldown_active": False,
                    "no_heartbeat_count": card_state.no_heartbeat_count,
                },
            )

        # 無心跳：累計計數
        card_state.no_heartbeat_count += 1

        if card_state.no_heartbeat_count >= HEARTBEAT_CHECK_COUNT:
            # 進入 SUSPECTED
            if card_state.state != WatchdogState.SUSPECTED:
                card_state.state = WatchdogState.SUSPECTED
                card_state.entered_suspected_at = now
                self.state.total_suspected += 1
                logger.warning(
                    f"[Watchdog] Card {card_id} entered SUSPECTED state "
                    f"(no_heartbeat_count={card_state.no_heartbeat_count})"
                )

            should_restart, check_reason = self._pre_restart_check(card_id, card_state)

            if should_restart:
                new_state = WatchdogState.RESTART
                card_state.state = new_state
                self.state.total_restarts += 1
                card_state.retry_count += 1

                cooldown_seconds = 0
                if card_state.retry_count <= len(RESTART_COOLDOWNS):
                    cooldown_sec = RESTART_COOLDOWNS[card_state.retry_count - 1]
                    cooldown_seconds = cooldown_sec
                    card_state.cooldown_until = now + cooldown_sec
                    logger.warning(
                        f"[Watchdog] Card {card_id} restart triggered "
                        f"(retry={card_state.retry_count}, cooldown={cooldown_sec}s)"
                    )
                else:
                    logger.error(
                        f"[Watchdog] Card {card_id} failed after {MAX_RETRIES} restart attempts"
                    )

                return (
                    new_state,
                    {
                        "old_state": old_state.value,
                        "state_changed": old_state != new_state,
                        "reason": check_reason,
                        "should_restart": True,
                        "retry_count": card_state.retry_count,
                        "cooldown_seconds": cooldown_seconds,
                        "cooldown_active": cooldown_seconds > 0,
                        "no_heartbeat_count": card_state.no_heartbeat_count,
                    },
                )
            else:
                # pre_check 未通過，繼續觀察
                new_state = WatchdogState.SUSPECTED
                return (
                    new_state,
                    {
                        "old_state": old_state.value,
                        "state_changed": old_state != new_state,
                        "reason": f"pre_check_failed: {check_reason}",
                        "should_restart": False,
                        "cooldown_active": False,
                        "no_heartbeat_count": card_state.no_heartbeat_count,
                    },
                )

        # 無心跳但尚未達到閾值
        return (
            card_state.state,
            {
                "old_state": old_state.value,
                "state_changed": False,
                "reason": f"no_heartbeat ({card_state.no_heartbeat_count}/{HEARTBEAT_CHECK_COUNT})",
                "should_restart": False,
                "cooldown_active": False,
                "no_heartbeat_count": card_state.no_heartbeat_count,
            },
        )

    def _pre_restart_check(
        self, card_id: int, card_state: CardWatchdogState
    ) -> Tuple[bool, str]:
        """三階段 pre-check 防誤判。

        三階段防誤判機制確保進程卡死判定的準確性。任一階段檢測到活躍即中止檢查、
        重置 SUSPECTED 計數並 return False，避免誤重啟。

        **Stage 1: Process alive 檢查**
        - 驗證進程是否仍在運行（通過心跳）
        - 閾值：距今 < WATCHDOG_HEARTBEAT_TIMEOUT (60s)
        - 活躍判定：有心跳記錄，距離小於 60 秒

        **Stage 2: Heartbeat age 檢查（帶 grace period）**
        - 檢查最後活動時間是否在 grace period 寬限期內
        - 寬限期：WATCHDOG_HEARTBEAT_TIMEOUT + WATCHDOG_GRACE_PERIOD (60 + 30 = 90s)
        - 活躍判定：距今 < 90 秒（在 Stage 1 超時後還有額外寬限期，用於處理大型任務心跳拉長）
        - 使用場景：npm install、git clone 等長時間操作，任務執行中心跳可能 60~90 秒無更新

        **Stage 3: Task queue check**
        - 檢查卡片是否還在任務隊列中
        - 活躍判定：卡片仍在待處理隊列或有活躍的相關操作

        Returns:
            (should_restart, reason)
        """
        now = time.time()

        # ── Stage 1: Heartbeat alive 檢查 ──
        last_hb = self.get_heartbeat_fn(card_id)
        if last_hb:
            hb_age = now - last_hb
            if hb_age < WATCHDOG_HEARTBEAT_TIMEOUT:
                card_state.no_heartbeat_count = 0
                card_state.state = WatchdogState.BUSY
                logger.debug(
                    f"[Watchdog] Card {card_id} Stage 1 passed: heartbeat alive ({hb_age:.1f}s ago)"
                )
                return False, f"stage1_heartbeat_alive ({hb_age:.1f}s ago)"

        # ── Stage 2: Grace period 寬限期檢查 ──
        grace_period_limit = WATCHDOG_HEARTBEAT_TIMEOUT + WATCHDOG_GRACE_PERIOD
        if last_hb:
            hb_age = now - last_hb
            if hb_age < grace_period_limit:
                card_state.no_heartbeat_count = 0
                card_state.state = WatchdogState.BUSY
                logger.debug(
                    f"[Watchdog] Card {card_id} Stage 2 passed: heartbeat within grace period "
                    f"({hb_age:.1f}s < {grace_period_limit}s)"
                )
                return False, f"stage2_within_grace_period ({hb_age:.1f}s < {grace_period_limit}s)"

        # ── Stage 3: Active process pool 檢查 ──
        has_active_process = self._check_active_process(card_id)
        if has_active_process:
            logger.debug(f"[Watchdog] Card {card_id} Stage 3 passed: active process still in pool")
            return False, "stage3_active_process_in_pool"

        # 三階段皆未通過，確認重啟
        suspected_duration = (
            now - card_state.entered_suspected_at
            if card_state.entered_suspected_at
            else 0.0
        )
        suspected_str = (
            f"{suspected_duration:.0f}s"
            if card_state.entered_suspected_at
            else "unknown"
        )
        logger.warning(
            f"[Watchdog] Card {card_id} all pre-check stages passed, confirming RESTART "
            f"(last_hb={last_hb}, suspected_for={suspected_str})"
        )
        return True, "all_stages_confirm_restart"

    def _check_active_process(self, card_id: int) -> bool:
        """檢查是否存在活躍的進程對應該卡片。

        通過 process_pool 實例檢查進程隊列中是否有該卡片的活躍進程。
        如果未提供 process_pool，默認返回 False（保守處理）。

        Args:
            card_id: 卡片 ID

        Returns:
            True if 進程池中有活躍進程對應該卡片，否則 False
        """
        if not self.process_pool:
            return False

        try:
            if hasattr(self.process_pool, "has_active_process"):
                return self.process_pool.has_active_process(card_id)
            if hasattr(self.process_pool, "active_count"):
                return self.process_pool.active_count() > 0
            logger.warning(
                "[Watchdog] process_pool 未實現必要的檢查接口 (has_active_process 或 active_count)"
            )
            return False
        except Exception as e:
            logger.error(f"[Watchdog] Error checking active process for card {card_id}: {e}")
            return False

    def reset_card(self, card_id: int) -> None:
        """重置單張卡片的 Watchdog 狀態（卡片完成或刪除時調用）。"""
        if card_id in self.state.card_states:
            del self.state.card_states[card_id]
            logger.debug(f"[Watchdog] Card {card_id} state reset")

    def reset_all(self) -> None:
        """重置所有 Watchdog 狀態（Worker 啟動時調用）。"""
        self.state.reset()
        logger.info("[Watchdog] All states reset")

    def check_fallback_triggered(self, card_id: int) -> bool:
        """檢查卡片是否應進入 fallback（3 次重啟失敗）。

        Returns:
            True if retry_count >= MAX_RETRIES（已達到最大重試次數）
        """
        if card_id not in self.state.card_states:
            return False

        card_state = self.state.card_states[card_id]
        if card_state.retry_count >= MAX_RETRIES:
            self.state.total_fallbacks += 1
            logger.error(
                f"[Watchdog] Card {card_id} fallback triggered after "
                f"{card_state.retry_count} restart attempts"
            )
            return True
        return False

    def get_diagnostics(self, card_id: int) -> dict:
        """取得卡片的診斷資訊（用於 fallback 報告）。"""
        if card_id not in self.state.card_states:
            return {}

        card_state = self.state.card_states[card_id]
        now = time.time()

        diagnostics = {
            "card_id": card_id,
            "state": card_state.state.value,
            "retry_count": card_state.retry_count,
            "last_heartbeat_age": (
                now - card_state.last_heartbeat_time
                if card_state.last_heartbeat_time
                else None
            ),
            "no_heartbeat_count": card_state.no_heartbeat_count,
            "entered_suspected_at": card_state.entered_suspected_at,
            "suspected_duration": (
                now - card_state.entered_suspected_at
                if card_state.entered_suspected_at
                else None
            ),
        }
        return diagnostics

    def get_stats(self) -> dict:
        """取得 Watchdog 全局統計資訊。"""
        return {
            "total_checks": self.state.total_checks,
            "total_suspected": self.state.total_suspected,
            "total_restarts": self.state.total_restarts,
            "total_fallbacks": self.state.total_fallbacks,
            "active_cards": len(self.state.card_states),
        }
