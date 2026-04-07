"""Provider 介面抽象 + OpenAI Provider 單元測試"""
import json

import pytest

from app.core.executor.provider_base import BaseProvider, ProviderMeta
from app.core.executor.provider_openai import OpenAIProvider
from app.core.executor.providers import get_provider, register_provider, _PROVIDER_REGISTRY


# ── ProviderMeta ──────────────────────────────────────────────


def test_provider_meta_defaults():
    meta = ProviderMeta(name="test")
    assert meta.name == "test"
    assert meta.default_model == ""
    assert meta.stream_json is False
    assert meta.json_output is False
    assert meta.stdin_prompt is False


def test_provider_meta_frozen():
    meta = ProviderMeta(name="test")
    with pytest.raises(AttributeError):
        meta.name = "changed"


# ── BaseProvider ABC ──────────────────────────────────────────


def test_base_provider_cannot_instantiate():
    """BaseProvider 是 ABC，不能直接實例化。"""
    with pytest.raises(TypeError):
        BaseProvider()


class _StubProvider(BaseProvider):
    """最小化實作，驗證介面合約。"""

    _meta = ProviderMeta(name="stub", default_model="stub-1", stream_json=True)

    @property
    def meta(self):
        return self._meta

    def build_command(self, prompt="", model="", **kwargs):
        return (["stub-cli", model or self._meta.default_model], False)

    def parse_stream_line(self, line):
        return line.strip() or None

    def parse_output(self, output):
        return {"result_text": output}


def test_stub_provider_satisfies_interface():
    p = _StubProvider()
    assert p.meta.name == "stub"
    cmd, stdin = p.build_command(model="stub-2")
    assert cmd == ["stub-cli", "stub-2"]
    assert stdin is False
    assert p.parse_stream_line("hello") == "hello"
    assert p.parse_stream_line("") is None
    assert p.parse_output("ok") == {"result_text": "ok"}


def test_to_legacy_config():
    p = _StubProvider()
    cfg = p.to_legacy_config()
    assert cfg["cmd_base"] == ["stub"]
    assert cfg["stream_json"] is True
    assert cfg["default_model"] == "stub-1"
    assert "json_output" not in cfg
    assert "stdin_prompt" not in cfg


# ── OpenAIProvider ────────────────────────────────────────────


@pytest.fixture
def openai_provider():
    return OpenAIProvider()


class TestOpenAIProviderMeta:
    def test_name(self, openai_provider):
        assert openai_provider.meta.name == "openai"

    def test_default_model(self, openai_provider):
        assert openai_provider.meta.default_model == "gpt-4o"

    def test_stream_json(self, openai_provider):
        assert openai_provider.meta.stream_json is True

    def test_stdin_prompt(self, openai_provider):
        assert openai_provider.meta.stdin_prompt is True


class TestOpenAIBuildCommand:
    def test_default_model(self, openai_provider):
        cmd, stdin = openai_provider.build_command()
        assert cmd == ["python", "scripts/openai_stream_chat.py", "--model", "gpt-4o"]
        assert stdin is True

    def test_custom_model(self, openai_provider):
        cmd, _ = openai_provider.build_command(model="gpt-4o-mini")
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-4o-mini"

    def test_mode_does_not_change_command(self, openai_provider):
        cmd_task, _ = openai_provider.build_command(mode="task")
        cmd_chat, _ = openai_provider.build_command(mode="chat")
        assert cmd_task == cmd_chat


class TestOpenAIParseStreamLine:
    def test_stream_json_format(self, openai_provider):
        line = json.dumps({
            "type": "assistant",
            "content": [{"type": "text", "text": "Hello"}],
        })
        assert openai_provider.parse_stream_line(line) == "Hello"

    def test_stream_json_non_assistant(self, openai_provider):
        line = json.dumps({"type": "result", "result": "done"})
        assert openai_provider.parse_stream_line(line) is None

    def test_sse_format(self, openai_provider):
        line = 'data: {"choices":[{"delta":{"content":"World"}}]}'
        assert openai_provider.parse_stream_line(line) == "World"

    def test_sse_done(self, openai_provider):
        assert openai_provider.parse_stream_line("data: [DONE]") is None

    def test_sse_empty_delta(self, openai_provider):
        line = 'data: {"choices":[{"delta":{}}]}'
        assert openai_provider.parse_stream_line(line) is None

    def test_empty_line(self, openai_provider):
        assert openai_provider.parse_stream_line("") is None
        assert openai_provider.parse_stream_line("  ") is None

    def test_invalid_json(self, openai_provider):
        assert openai_provider.parse_stream_line("{broken") is None

    def test_sse_invalid_json(self, openai_provider):
        assert openai_provider.parse_stream_line("data: {broken") is None


class TestOpenAIParseOutput:
    def test_full_output(self, openai_provider):
        output = json.dumps({
            "result_text": "done",
            "model": "gpt-4o",
            "duration_ms": 500,
            "cost_usd": 0.01,
            "input_tokens": 100,
            "output_tokens": 50,
        })
        result = openai_provider.parse_output(output)
        assert result["result_text"] == "done"
        assert result["model"] == "gpt-4o"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cost_usd"] == 0.01

    def test_partial_output(self, openai_provider):
        output = json.dumps({"result_text": "hi"})
        result = openai_provider.parse_output(output)
        assert result["result_text"] == "hi"
        assert result["input_tokens"] == 0

    def test_invalid_json(self, openai_provider):
        assert openai_provider.parse_output("not json") == {}


class TestOpenAILegacyCompat:
    def test_to_legacy_config(self, openai_provider):
        cfg = openai_provider.to_legacy_config()
        assert cfg["cmd_base"] == ["openai"]
        assert cfg["stream_json"] is True
        assert cfg["default_model"] == "gpt-4o"
        assert cfg["stdin_prompt"] is True


# ── Registry ─────────────────────────────────────────────────


class TestProviderRegistry:
    def test_get_openai_provider(self):
        p = get_provider("openai")
        assert p is not None
        assert isinstance(p, OpenAIProvider)
        assert p.meta.name == "openai"

    def test_get_unknown_provider(self):
        assert get_provider("unknown_xyz") is None

    def test_register_custom_provider(self):
        stub = _StubProvider()
        register_provider(stub)
        assert get_provider("stub") is stub
        # 清理
        _PROVIDER_REGISTRY.pop("stub", None)

    def test_get_provider_returns_same_instance(self):
        p1 = get_provider("openai")
        p2 = get_provider("openai")
        assert p1 is p2
