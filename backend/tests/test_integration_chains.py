"""端到端整合測試 — 驗證三條核心鏈路的跨模組交互行為。

Chain 1: StreamEmitter 串流管線（emitter + stream_parsers）
Chain 2: model_router → build_command 路由鏈
Chain 3: data_classifier → prompt_hardening 安全鏈
"""
import json

import pytest

from app.core.executor.emitter import (
    StreamEmitter,
    NullTarget,
    StreamTarget,
    StreamEvent,
    parse_stream_event,
    clean_ansi,
)
from app.core.model_router import resolve_model_by_tags
from app.core.executor.providers import build_command, get_provider_config
from app.core.data_classifier import classify, scan, sanitize, restore, SecurityLevel
from app.core.prompt_hardening import harden_prompt, SECURITY_REMINDER


# ════════════════════════════════════════════════════════
# Chain 1: StreamEmitter 串流管線
# ════════════════════════════════════════════════════════

class RecordingTarget:
    """測試用 target — 記錄所有收到的事件。"""
    def __init__(self):
        self.events: list[StreamEvent] = []

    def handle(self, event: StreamEvent) -> None:
        self.events.append(event)


def _make_system_line():
    return json.dumps({"type": "system", "subtype": "init"})


def _make_short_text_line(text: str):
    """短文字（<200字）→ parse_tool_call 攔截為 kind="output" + 💬 前綴。
    不累積到 collected_text（只有 kind="text" 才累積）。"""
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    })


def _make_long_text_line(text: str):
    """長文字（>=200字）→ parse_tool_call 跳過 → parse_stream_json_text 處理為 kind="text"。
    會累積到 collected_text。"""
    assert len(text) >= 200, "長文字 fixture 須 >= 200 字"
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    })


def _make_tool_line(tool_name: str, tool_input: dict):
    return json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": tool_name, "input": tool_input},
        ]},
    })


def _make_result_line(input_tokens=100, output_tokens=50, cost=0.01):
    return json.dumps({
        "type": "result",
        "result": "done",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        "duration_ms": 5000,
        "total_cost_usd": cost,
    })


class TestStreamEmitterPipeline:
    """Chain 1: 完整串流管線 — raw JSON → parse → target 分發 → 累積。"""

    def test_full_stream_sequence(self):
        """模擬完整任務輸出：system → short_text → tool_call → long_text → result"""
        recorder = RecordingTarget()
        emitter = StreamEmitter(targets=[recorder, NullTarget()])

        long_text = "分析完成。" + "x" * 200  # >= 200 字 → kind="text"

        lines = [
            _make_system_line(),
            _make_short_text_line("開始分析程式碼..."),  # kind="output"
            _make_tool_line("Read", {"file_path": "/tmp/test.py"}),
            _make_long_text_line(long_text),  # kind="text"
            _make_result_line(input_tokens=200, output_tokens=80, cost=0.03),
        ]

        for line in lines:
            emitter.emit_raw(line)

        # system 行被過濾，其餘 4 個事件分發
        assert len(recorder.events) == 4

        # 短文字（<200 字）→ kind="output"（💬 前綴），不累積到 collected_text
        assert recorder.events[0].kind == "output"
        assert "💬" in recorder.events[0].content

        # 長文字（>=200 字）→ kind="text"，累積到 collected_text
        assert emitter.collected_text == long_text

        # token info 來自 result 行
        assert emitter.token_info.get("input_tokens") == 200
        assert emitter.token_info.get("output_tokens") == 80

    def test_system_and_ratelimit_filtered(self):
        """system 和 rate_limit 事件不應傳給 target。"""
        recorder = RecordingTarget()
        emitter = StreamEmitter(targets=[recorder])

        emitter.emit_raw(json.dumps({"type": "system", "subtype": "init"}))
        emitter.emit_raw(json.dumps({"type": "rate_limit_event", "retry_after": 5}))
        emitter.emit_raw(json.dumps({"type": "user"}))

        assert len(recorder.events) == 0
        assert emitter.collected_text == ""

    def test_malformed_json_ignored(self):
        """無效 JSON 不應導致錯誤。"""
        recorder = RecordingTarget()
        emitter = StreamEmitter(targets=[recorder])

        emitter.emit_raw("not json at all")
        emitter.emit_raw("{incomplete json")
        emitter.emit_raw("")

        assert len(recorder.events) == 0

    def test_heartbeat_dispatched(self):
        """心跳事件應分發給所有 target。"""
        recorder = RecordingTarget()
        emitter = StreamEmitter(targets=[recorder])

        emitter.emit_heartbeat(30)

        assert len(recorder.events) == 1
        assert recorder.events[0].kind == "heartbeat"
        assert "30s" in recorder.events[0].content

    def test_target_error_isolation(self):
        """一個 target 出錯不應影響其他 target。"""
        class ExplodingTarget:
            def handle(self, event):
                raise RuntimeError("boom")

        recorder = RecordingTarget()
        emitter = StreamEmitter(targets=[ExplodingTarget(), recorder])

        emitter.emit_raw(_make_short_text_line("hello"))

        # recorder 仍然收到事件（短文字 → kind="output" + 💬 前綴）
        assert len(recorder.events) == 1
        assert "hello" in recorder.events[0].content

    def test_empty_targets(self):
        """無 target 的 emitter 不應出錯。"""
        emitter = StreamEmitter(targets=[])
        long_text = "a" * 200
        emitter.emit_raw(_make_long_text_line(long_text))
        emitter.emit_heartbeat(10)
        assert emitter.collected_text == long_text

    def test_ansi_cleaning(self):
        """ANSI escape codes 應被清除。"""
        dirty = "\x1b[31mred text\x1b[0m normal"
        assert clean_ansi(dirty) == "red text normal"

    def test_multiple_result_lines_last_wins(self):
        """多個 result 行時，最後一個的 token_info 覆蓋前者。"""
        emitter = StreamEmitter(targets=[NullTarget()])
        emitter.emit_raw(_make_result_line(input_tokens=100, output_tokens=50))
        emitter.emit_raw(_make_result_line(input_tokens=300, output_tokens=150))

        assert emitter.token_info.get("input_tokens") == 300


# ════════════════════════════════════════════════════════
# Chain 2: model_router → build_command 路由鏈
# ════════════════════════════════════════════════════════

class TestModelRouterToBuildCommand:
    """Chain 2: tag 路由 → 命令建構的端到端驗證。"""

    @pytest.mark.parametrize("tags,expected_model", [
        (["Refactor", "backend"], "haiku"),
        (["simple"], "haiku"),
        (["AI-Haiku"], "haiku"),
        (["complex", "P0"], "opus"),
        (["AI-Opus"], "opus"),
        (["AI-Sonnet"], "sonnet"),
    ])
    def test_tags_to_claude_command(self, tags, expected_model):
        """tags → model → claude CLI 命令包含正確的 --model 參數。"""
        model = resolve_model_by_tags(tags)
        cmd, stdin_prompt = build_command("claude", prompt="test", model=model, mode="task")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == expected_model
        assert stdin_prompt is True  # task 模式用 stdin

    def test_no_matching_tag_uses_provider_default(self):
        """無匹配 tag 時 build_command 用 provider 預設模型。"""
        model = resolve_model_by_tags(["docs", "minor"])
        assert model is None

        cmd, _ = build_command("claude", prompt="test", model=model or "", mode="task")
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "sonnet"  # claude task 預設

    def test_gemini_routing(self):
        """tags → model → gemini CLI 命令。"""
        model = resolve_model_by_tags(["AI-Haiku"], default="gemini-2.5-flash")
        # AI-Haiku 匹配 → haiku（claude 模型名），但 gemini 需要自己的模型名
        # 這裡驗證 resolve_model_by_tags 的結果傳入 build_command
        cmd, stdin_prompt = build_command("gemini", prompt="test", model=model or "")
        assert "gemini" in cmd[0]
        assert "-p" in cmd
        assert stdin_prompt is False

    def test_ollama_routing(self):
        """ollama provider 使用 stdin_prompt。"""
        cmd, stdin_prompt = build_command("ollama", prompt="test", model="llama3.1:8b")
        assert stdin_prompt is True
        assert "llama3.1:8b" in cmd

    def test_claude_chat_mode_uses_p_flag(self):
        """chat 模式的 claude 命令應使用 -p 傳 prompt。"""
        cmd, stdin_prompt = build_command(
            "claude", prompt="hello", model="sonnet", mode="chat",
        )
        assert "-p" in cmd
        assert "hello" in cmd
        assert stdin_prompt is False

    def test_claude_task_mode_no_p_flag(self):
        """task 模式的 claude 命令不應有 -p（用 stdin）。"""
        cmd, stdin_prompt = build_command(
            "claude", prompt="do something", model="opus", mode="task",
        )
        assert "-p" not in cmd
        assert stdin_prompt is True

    def test_mcp_config_injection(self):
        """MCP config 路徑應注入到命令中。"""
        cmd, _ = build_command(
            "claude", prompt="test", model="sonnet",
            mcp_config_path="/tmp/mcp.json",
        )
        assert "--mcp-config" in cmd
        assert "/tmp/mcp.json" in cmd

    def test_resume_session(self):
        """resume session ID 應注入到命令中。"""
        cmd, _ = build_command(
            "claude", prompt="test", model="sonnet",
            resume_session_id="abc-123",
        )
        assert "--resume" in cmd
        assert "abc-123" in cmd


# ════════════════════════════════════════════════════════
# Chain 3: data_classifier → prompt_hardening 安全鏈
# ════════════════════════════════════════════════════════

class TestSecurityChain:
    """Chain 3: 敏感資料偵測 → 去敏 → 安全注入的端到端驗證。"""

    def test_s3_detected_sanitized_hardened(self):
        """S3 文字（API key）→ classify → sanitize → harden 完整鏈。"""
        prompt = "請用這個 key 部署：sk-ant-api03-abcdefghijklmnopqrstuvwxyz"

        # Step 1: classify
        level = classify(prompt)
        assert level == SecurityLevel.S3

        # Step 2: sanitize
        sanitized, mapping = sanitize(prompt)
        assert "sk-ant-" not in sanitized
        assert "REDACTED" in sanitized

        # Step 3: harden
        hardened = harden_prompt(sanitized, "/tmp/project")
        assert "security-reminder" in hardened
        assert "sk-ant-" not in hardened
        assert "禁止讀寫 .env" in hardened

        # Step 4: restore（驗證 mapping 可還原）
        restored = restore(sanitized, mapping)
        assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz" in restored

    def test_s2_detected_but_passthrough(self):
        """S2 文字（email）→ classify 為 S2，可選擇不去敏直接 harden。"""
        prompt = "寄信給 alice@example.com 通知"
        level = classify(prompt)
        assert level == SecurityLevel.S2

        # S2 可以不去敏，直接 harden
        hardened = harden_prompt(prompt, "/tmp/project")
        assert "alice@example.com" in hardened
        assert "security-reminder" in hardened

    def test_s1_clean_prompt(self):
        """S1 文字（安全）→ classify 為 S1，harden 仍附加安全提醒。"""
        prompt = "請幫我重構 utils.py 中的重複函式"
        level = classify(prompt)
        assert level == SecurityLevel.S1

        hardened = harden_prompt(prompt, "/tmp/project")
        assert prompt in hardened
        assert "security-reminder" in hardened

    def test_empty_prompt_not_hardened(self):
        """空 prompt 不附加安全提醒。"""
        assert harden_prompt("", "/tmp/project") == ""

    def test_multiple_s3_all_sanitized(self):
        """多個 S3 敏感值全部被去敏。"""
        prompt = (
            "keys: sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaa "
            "and sk-proj-bbbbbbbbbbbbbbbbbbbbbb "
            "password=MySecret123!"
        )
        level = classify(prompt)
        assert level == SecurityLevel.S3

        sanitized, mapping = sanitize(prompt)
        matches = scan(prompt)
        assert len(matches) >= 2  # 至少 2 個 S3 匹配

        hardened = harden_prompt(sanitized, "/tmp/project")
        assert "sk-ant-" not in hardened
        assert "MySecret123" not in hardened

    def test_sanitize_restore_roundtrip(self):
        """去敏→還原的完整 roundtrip。"""
        original = "token: ghp_abcdefghijklmnopqrstuvwx"
        sanitized, mapping = sanitize(original)
        assert "ghp_" not in sanitized
        restored = restore(sanitized, mapping)
        assert restored == original
