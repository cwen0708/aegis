"""Directive Protocol — 類型系統與端點驗證測試（TDD 先紅後綠）"""
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.directives import (
    DirectiveType,
    UpdateCodePayload,
    RunTaskPayload,
    AskUserPayload,
    validate_directive,
)


# ── enum 完整性 ──────────────────────────────────────────

def test_directive_type_enum_has_core_types():
    """至少 15 個類型，並覆蓋程式碼/互動/任務/檔案/UI 五大類"""
    values = {dt.value for dt in DirectiveType}
    assert len(values) >= 15

    # 五大類核心成員必須存在
    expected_core = {
        "update_code", "run_task", "open_file", "show_diff",
        "ask_user", "notify", "prompt", "confirm",
        "card_update", "card_comment", "card_move",
        "upload_file", "download_file",
        "navigate", "highlight",
    }
    assert expected_core.issubset(values)


# ── payload schema 驗證 ──────────────────────────────────

class TestUpdateCodePayload:
    def test_valid_payload_passes(self):
        ok, err = validate_directive("update_code", {
            "file_path": "src/foo.py",
            "content": "print('hi')",
            "mode": "replace",
        })
        assert ok is True
        assert err is None

    def test_invalid_mode_rejected(self):
        ok, err = validate_directive("update_code", {
            "file_path": "src/foo.py",
            "content": "print('hi')",
            "mode": "overwrite",  # 不在 Literal 範圍
        })
        assert ok is False
        assert err is not None
        assert "update_code" in err

    def test_missing_required_field_rejected(self):
        ok, err = validate_directive("update_code", {
            "file_path": "src/foo.py",
            "mode": "replace",
            # 缺 content
        })
        assert ok is False
        assert err is not None


class TestAskUserPayload:
    def test_valid_minimal_payload(self):
        ok, err = validate_directive("ask_user", {"question": "繼續嗎？"})
        assert ok is True
        assert err is None

    def test_valid_full_payload(self):
        ok, err = validate_directive("ask_user", {
            "question": "選擇方案",
            "choices": ["A", "B"],
            "timeout_sec": 30,
        })
        assert ok is True

    def test_missing_question_rejected(self):
        ok, err = validate_directive("ask_user", {"choices": ["A"]})
        assert ok is False
        assert err is not None


class TestRunTaskPayload:
    def test_valid_minimal_payload(self):
        ok, err = validate_directive("run_task", {"command": "pytest"})
        assert ok is True

    def test_valid_full_payload(self):
        ok, err = validate_directive("run_task", {
            "task_id": 42,
            "command": "pytest -k foo",
            "working_dir": "/tmp/proj",
        })
        assert ok is True

    def test_missing_command_rejected(self):
        ok, err = validate_directive("run_task", {"task_id": 1})
        assert ok is False
        assert err is not None


# ── 向後相容：未知 type 一律放行 ─────────────────────────

def test_unknown_directive_is_backward_compatible():
    ok, err = validate_directive("legacy_custom_action", {"foo": "bar"})
    assert ok is True
    assert err is None

    # 即使 params 完全空亦放行
    ok, err = validate_directive("future_unseen_type", {})
    assert ok is True
    assert err is None


# ── /internal/directive 端點整合 ─────────────────────────

@pytest.fixture
def client():
    """構造最小 FastAPI app，僅掛載 runner.router 以避開 main.py 的 lifespan"""
    from app.api import runner as runner_routes

    app = FastAPI()
    app.include_router(runner_routes.router)
    return TestClient(app)


def test_internal_directive_endpoint_rejects_invalid_payload(client):
    """已知 type 但 payload 錯誤 → 422"""
    with patch("app.core.ws_manager.broadcast_directive", new=AsyncMock()) as mock_bc:
        resp = client.post("/internal/directive", json={
            "action": "update_code",
            "params": {"file_path": "a.py", "mode": "BAD_MODE"},
        })
    assert resp.status_code == 422
    mock_bc.assert_not_called()


def test_internal_directive_endpoint_accepts_unknown_action(client):
    """未知 action → 200，照舊廣播"""
    with patch("app.core.ws_manager.broadcast_directive", new=AsyncMock()) as mock_bc:
        resp = client.post("/internal/directive", json={
            "action": "some_legacy_action",
            "params": {"anything": 1},
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_bc.assert_awaited_once()


def test_internal_directive_endpoint_accepts_valid_known(client):
    """已知 type + 合法 payload → 200，廣播被呼叫"""
    with patch("app.core.ws_manager.broadcast_directive", new=AsyncMock()) as mock_bc:
        resp = client.post("/internal/directive", json={
            "action": "ask_user",
            "params": {"question": "OK?"},
        })
    assert resp.status_code == 200
    mock_bc.assert_awaited_once()
