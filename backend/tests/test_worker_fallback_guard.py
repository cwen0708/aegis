"""Bug #13145: Worker fallback guard

驗證 `_is_card_already_success(card_id)` — 當 Claude CLI subprocess 被 SIGTERM
（exit=143）但 run_task 內部已把 DB 標為 success 時，外層迴圈不應觸發帳號
fallback 或 provider failover，避免整個 Phase 重跑。
"""
from unittest.mock import MagicMock, patch

import pytest


class _FakeSessionContext:
    """模擬 `with Session(engine) as session:` 的 context manager"""

    def __init__(self, stored_status):
        self._stored_status = stored_status

    def __enter__(self):
        sess = MagicMock()
        if self._stored_status is None:
            sess.get.return_value = None
        else:
            idx = MagicMock()
            idx.status = self._stored_status
            sess.get.return_value = idx
        return sess

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_session(stored_status):
    return patch("worker.Session", return_value=_FakeSessionContext(stored_status))


class TestIsCardAlreadySuccess:
    """直接驗證 helper 行為"""

    def test_returns_true_when_status_is_success(self):
        from worker import _is_card_already_success

        with _patch_session("success"):
            assert _is_card_already_success(42) is True

    def test_returns_false_when_status_is_running(self):
        from worker import _is_card_already_success

        with _patch_session("running"):
            assert _is_card_already_success(42) is False

    def test_returns_false_when_status_is_failed(self):
        from worker import _is_card_already_success

        with _patch_session("failed"):
            assert _is_card_already_success(42) is False

    def test_returns_false_when_card_missing(self):
        from worker import _is_card_already_success

        with _patch_session(None):
            assert _is_card_already_success(42) is False


class TestFallbackGuardBehaviour:
    """驗證 fallback 迴圈中 `_is_card_already_success` 被呼叫時會早退"""

    def test_guard_skips_account_fallback_when_db_success(self):
        """模擬 account fallback 第二輪時 DB 已 success，應該早退不再重試"""
        from worker import _is_card_already_success

        # 第一次呼叫（attempt_idx=1 前）DB 已是 success
        with _patch_session("success"):
            assert _is_card_already_success(101) is True

        # 反之，若 DB 仍 running，才應該 fallback
        with _patch_session("running"):
            assert _is_card_already_success(101) is False

    def test_guard_skips_provider_failover_when_db_success(self):
        """模擬進入 provider failover 前 DB 已 success，外層 guard 應阻擋"""
        from worker import _is_card_already_success

        with _patch_session("success"):
            assert _is_card_already_success(202) is True
