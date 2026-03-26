"""llm_audit 單元測試 — LLMCallRecord 序列化 + LLMAuditContext 行為"""
import json
import time
from pathlib import Path

from app.core.llm_audit import LLMCallRecord, log_llm_call, LLMAuditContext


# ── LLMCallRecord.to_dict ────────────────────────────────────

def test_record_to_dict_full():
    r = LLMCallRecord(
        provider="claude", model="claude-3-opus", card_id=42,
        member_id=1, start_time=1000.0, end_time=1005.0,
        input_tokens=200, output_tokens=80,
        status="success", cost_usd=0.05,
        cache_read_tokens=10, cache_creation_tokens=5,
        duration_ms=5000, session_id="sess-123",
    )
    d = r.to_dict()
    assert d["provider"] == "claude"
    assert d["model"] == "claude-3-opus"
    assert d["card_id"] == 42
    assert d["input_tokens"] == 200
    assert d["output_tokens"] == 80
    assert d["status"] == "success"
    assert d["cost_usd"] == 0.05
    assert d["duration_ms"] == 5000
    assert d["session_id"] == "sess-123"


def test_record_to_dict_omits_empty():
    """空值欄位不應出現在輸出中"""
    r = LLMCallRecord(provider="claude", status="success")
    d = r.to_dict()
    assert "model" not in d
    assert "card_id" not in d
    assert "input_tokens" not in d
    assert "error" not in d
    assert d["provider"] == "claude"
    assert d["status"] == "success"


def test_record_to_dict_keeps_member_id_none():
    """member_id=None 應被移除"""
    r = LLMCallRecord(provider="openai", status="error", member_id=None)
    d = r.to_dict()
    assert "member_id" not in d


# ── log_llm_call ─────────────────────────────────────────────

def test_log_llm_call_writes_jsonl(tmp_path):
    out = tmp_path / "audit.jsonl"
    r = LLMCallRecord(provider="claude", model="opus", input_tokens=100, status="success")
    log_llm_call(r, path=out)

    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["provider"] == "claude"
    assert data["model"] == "opus"
    assert data["input_tokens"] == 100


def test_log_llm_call_appends(tmp_path):
    out = tmp_path / "audit.jsonl"
    log_llm_call(LLMCallRecord(provider="claude", status="success"), path=out)
    log_llm_call(LLMCallRecord(provider="openai", status="success"), path=out)

    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["provider"] == "claude"
    assert json.loads(lines[1])["provider"] == "openai"


def test_log_llm_call_creates_parent_dirs(tmp_path):
    out = tmp_path / "sub" / "dir" / "audit.jsonl"
    log_llm_call(LLMCallRecord(provider="test", status="success"), path=out)
    assert out.exists()


# ── LLMAuditContext ──────────────────────────────────────────

def test_context_auto_timing(tmp_path):
    out = tmp_path / "audit.jsonl"
    with LLMAuditContext(provider="claude", card_id=1, audit_path=out) as ctx:
        time.sleep(0.05)
        ctx.record.status = "success"

    data = json.loads(out.read_text().strip())
    assert data["provider"] == "claude"
    assert data["card_id"] == 1
    assert data["status"] == "success"
    assert data["duration_ms"] >= 40  # 至少 40ms


def test_context_captures_error(tmp_path):
    out = tmp_path / "audit.jsonl"
    try:
        with LLMAuditContext(provider="claude", audit_path=out) as ctx:
            raise ValueError("test error")
    except ValueError:
        pass

    data = json.loads(out.read_text().strip())
    assert data["status"] == "error"
    assert "test error" in data["error"]


def test_context_does_not_swallow_exception(tmp_path):
    out = tmp_path / "audit.jsonl"
    caught = False
    try:
        with LLMAuditContext(provider="claude", audit_path=out):
            raise RuntimeError("boom")
    except RuntimeError:
        caught = True

    assert caught, "LLMAuditContext should not swallow exceptions"


def test_context_default_status_success(tmp_path):
    out = tmp_path / "audit.jsonl"
    with LLMAuditContext(provider="claude", audit_path=out):
        pass

    data = json.loads(out.read_text().strip())
    assert data["status"] == "success"


def test_context_preserves_explicit_status(tmp_path):
    """若在 with 中已設定 status，不應被覆蓋"""
    out = tmp_path / "audit.jsonl"
    with LLMAuditContext(provider="claude", audit_path=out) as ctx:
        ctx.record.status = "aborted"

    data = json.loads(out.read_text().strip())
    assert data["status"] == "aborted"


# ── fill_from_token_info ─────────────────────────────────────

def test_fill_from_token_info(tmp_path):
    out = tmp_path / "audit.jsonl"
    token_info = {
        "model": "claude-3-sonnet",
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_usd": 0.02,
        "cache_read_tokens": 50,
        "cache_creation_tokens": 30,
        "session_id": "sess-abc",
    }
    with LLMAuditContext(provider="claude", card_id=99, audit_path=out) as ctx:
        ctx.record.status = "success"
        ctx.fill_from_token_info(token_info)

    data = json.loads(out.read_text().strip())
    assert data["model"] == "claude-3-sonnet"
    assert data["input_tokens"] == 500
    assert data["output_tokens"] == 200
    assert data["cost_usd"] == 0.02
    assert data["session_id"] == "sess-abc"


def test_fill_from_token_info_empty():
    """空 dict 不應改變 record"""
    ctx = LLMAuditContext(provider="claude")
    ctx.record.model = "original"
    ctx.fill_from_token_info({})
    assert ctx.record.model == "original"


def test_fill_from_token_info_none():
    """None 不應拋錯"""
    ctx = LLMAuditContext(provider="claude")
    ctx.fill_from_token_info(None)
    assert ctx.record.input_tokens == 0
