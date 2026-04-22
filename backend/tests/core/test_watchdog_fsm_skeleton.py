"""P0-SH-02 step 1 · CardWatchdogState 兩維度 FSM 骨架。

純結構擴充測試：新增 LifecycleState / HealthState Enum，擴充 CardWatchdogState 欄位。
不涉及 WatchdogMonitor 主迴圈，純型別與資料結構驗證。
"""
from app.core.watchdog import (
    CardWatchdogState,
    HealthState,
    LifecycleState,
    WatchdogState,
)


class TestLifecycleStateEnum:
    """LifecycleState 應包含 6 個進程生命週期狀態。"""

    def test_lifecycle_state_has_six_members(self):
        expected = {
            "STARTING",
            "RUNNING",
            "DEGRADED",
            "SUSPECTED",
            "RESTARTING",
            "CRASHED",
        }
        actual = {member.name for member in LifecycleState}
        assert actual == expected

    def test_lifecycle_state_values_are_lowercase_strings(self):
        assert LifecycleState.STARTING.value == "starting"
        assert LifecycleState.RUNNING.value == "running"
        assert LifecycleState.DEGRADED.value == "degraded"
        assert LifecycleState.SUSPECTED.value == "suspected"
        assert LifecycleState.RESTARTING.value == "restarting"
        assert LifecycleState.CRASHED.value == "crashed"


class TestHealthStateEnum:
    """HealthState 應包含 4 個健康狀態。"""

    def test_health_state_has_four_members(self):
        expected = {"HEALTHY", "STALE", "UNRESPONSIVE", "DEAD"}
        actual = {member.name for member in HealthState}
        assert actual == expected

    def test_health_state_values_are_lowercase_strings(self):
        assert HealthState.HEALTHY.value == "healthy"
        assert HealthState.STALE.value == "stale"
        assert HealthState.UNRESPONSIVE.value == "unresponsive"
        assert HealthState.DEAD.value == "dead"


class TestCardWatchdogStateDefaults:
    """CardWatchdogState 預設值驗證（向後相容）。"""

    def test_default_lifecycle_is_running(self):
        card = CardWatchdogState(card_id=1)
        assert card.lifecycle == LifecycleState.RUNNING

    def test_default_health_is_healthy(self):
        card = CardWatchdogState(card_id=1)
        assert card.health == HealthState.HEALTHY

    def test_legacy_state_field_default_is_busy(self):
        """向後相容：原 state 欄位預設值維持為 BUSY。"""
        card = CardWatchdogState(card_id=1)
        assert card.state == WatchdogState.BUSY


class TestCardWatchdogStateOverrides:
    """可顯式傳入 lifecycle / health 覆寫預設值。"""

    def test_can_override_lifecycle(self):
        card = CardWatchdogState(card_id=1, lifecycle=LifecycleState.STARTING)
        assert card.lifecycle == LifecycleState.STARTING

    def test_can_override_health(self):
        card = CardWatchdogState(card_id=1, health=HealthState.STALE)
        assert card.health == HealthState.STALE

    def test_can_override_both_lifecycle_and_health(self):
        card = CardWatchdogState(
            card_id=2,
            lifecycle=LifecycleState.SUSPECTED,
            health=HealthState.UNRESPONSIVE,
        )
        assert card.lifecycle == LifecycleState.SUSPECTED
        assert card.health == HealthState.UNRESPONSIVE
