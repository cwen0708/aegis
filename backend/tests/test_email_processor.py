"""email_processor 單元測試 — _parse_json_output / _match_project"""
import json
from unittest.mock import MagicMock

from app.core.email_processor import _parse_json_output, _match_project


# ── _parse_json_output ──────────────────────────────────────

def test_parse_json_plain():
    """正常 JSON 字串直接解析"""
    data = {"category": "actionable", "urgency": "high"}
    assert _parse_json_output(json.dumps(data)) == data


def test_parse_json_code_block_with_lang():
    """```json ... ``` code block 包裹"""
    raw = '```json\n{"category": "spam"}\n```'
    assert _parse_json_output(raw) == {"category": "spam"}


def test_parse_json_code_block_no_lang():
    """``` ... ``` 無語言標記的 code block"""
    raw = '```\n{"urgency": "low"}\n```'
    assert _parse_json_output(raw) == {"urgency": "low"}


def test_parse_json_surrounding_text():
    """JSON 前後有多餘文字，取 {...} 區段"""
    raw = 'Here is the result:\n{"summary": "ok"}\nDone.'
    assert _parse_json_output(raw) == {"summary": "ok"}


def test_parse_json_invalid():
    """非法 JSON 回傳 None"""
    assert _parse_json_output("this is not json at all") is None


def test_parse_json_empty():
    """空字串回傳 None"""
    assert _parse_json_output("") is None


def test_parse_json_nested():
    """巢狀 JSON 物件"""
    data = {
        "category": "actionable",
        "metadata": {"source": "gmail", "labels": ["important", "inbox"]},
    }
    assert _parse_json_output(json.dumps(data)) == data


# ── _match_project ──────────────────────────────────────────

def _make_project(pid: int, name: str, is_active: bool = True):
    """建立 mock Project 物件"""
    p = MagicMock()
    p.id = pid
    p.name = name
    p.is_active = is_active
    return p


def _mock_session(projects: list):
    """建立 mock Session，exec(...).all() 回傳指定專案列表"""
    session = MagicMock()
    session.exec.return_value.all.return_value = projects
    return session


def test_match_exact_keyword():
    """關鍵字完全匹配到 project name"""
    session = _mock_session([_make_project(1, "Aegis")])
    assert _match_project(session, ["aegis"]) == 1


def test_match_best_score():
    """多個關鍵字部分匹配，選分數最高的"""
    projects = [
        _make_project(1, "Aegis Backend"),
        _make_project(2, "Aegis Frontend Dashboard"),
    ]
    session = _mock_session(projects)
    # "frontend" + "dashboard" 各匹配 project 2 → score=2，project 1 score=0
    assert _match_project(session, ["frontend", "dashboard"]) == 2


def test_match_no_match():
    """無匹配回傳 None"""
    session = _mock_session([_make_project(1, "Aegis")])
    assert _match_project(session, ["unrelated"]) is None


def test_match_empty_keywords():
    """空關鍵字列表回傳 None"""
    session = MagicMock()
    assert _match_project(session, []) is None


def test_match_no_active_projects():
    """無 active 專案回傳 None"""
    session = _mock_session([])  # query 回傳空列表
    assert _match_project(session, ["aegis"]) is None
