"""Tests for save_cron_log delivery_error vs error_message separation.

Background: CronLog 原本只有統一的 error_message 欄位，無法區分
agent 執行失敗與投遞失敗（Telegram/Webhook）。此測試驗證新增
delivery_error 欄位後，save_cron_log 能正確分流兩種錯誤。
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import worker
from app.models.core import CronLog


@pytest.fixture
def tmp_engine(tmp_path, monkeypatch):
    """替換 worker.engine 指向臨時 SQLite，確保測試隔離。"""
    db_path = tmp_path / "cronlog.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(worker, "engine", engine)
    return engine


def _call_save(delivery_error: str = "", error_message: str = "", status: str = "success"):
    """以預設參數呼叫 save_cron_log，只改動要驗證的欄位。"""
    worker.save_cron_log(
        cron_job_id=1,
        cron_job_name="test-job",
        card_id=0,
        card_title="",
        project_id=1,
        project_name="p",
        provider="claude",
        member_id=None,
        status=status,
        output="",
        error_message=error_message,
        prompt_snapshot="",
        token_info={},
        stage_action="",
        delivery_error=delivery_error,
    )


def _read_log(engine) -> CronLog:
    with Session(engine) as session:
        row = session.exec(select(CronLog)).one()
        return row


def test_agent_error_only(tmp_engine):
    """Case A：agent 錯誤時 error_message 有值、delivery_error 為空字串。"""
    _call_save(error_message="agent crashed", status="error")
    log = _read_log(tmp_engine)
    assert log.error_message == "agent crashed"
    assert log.delivery_error == ""


def test_delivery_error_only(tmp_engine):
    """Case B：投遞失敗時 delivery_error 有值、error_message 為空字串。"""
    _call_save(delivery_error="telegram 404", status="error")
    log = _read_log(tmp_engine)
    assert log.error_message == ""
    assert log.delivery_error == "telegram 404"


def test_both_empty_on_success(tmp_engine):
    """Case C：成功時兩個欄位都是空字串。"""
    _call_save(status="success")
    log = _read_log(tmp_engine)
    assert log.error_message == ""
    assert log.delivery_error == ""
