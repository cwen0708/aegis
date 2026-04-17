"""Ralph Loop 單元測試 — parse_loop_signal / build_next_round_prompt"""
import pytest

from app.core.ralph_loop import LoopSignal, parse_loop_signal, build_next_round_prompt


# ========== parse_loop_signal ==========

class TestParseLoopSignal:
    """偵測 AI 輸出中的迭代控制信號。"""

    def test_continue_signal(self):
        output = "任務完成，需要繼續。\n<!-- loop:continue -->"
        assert parse_loop_signal(output) == LoopSignal.CONTINUE

    def test_done_signal(self):
        output = "所有工作完成。\n<!-- loop:done -->"
        assert parse_loop_signal(output) == LoopSignal.DONE

    def test_no_signal(self):
        output = "普通輸出，沒有任何 loop 標記。"
        assert parse_loop_signal(output) == LoopSignal.NONE

    def test_empty_string(self):
        assert parse_loop_signal("") == LoopSignal.NONE

    def test_multiple_signals_takes_last(self):
        output = "第一步\n<!-- loop:continue -->\n第二步\n<!-- loop:done -->"
        assert parse_loop_signal(output) == LoopSignal.DONE

    def test_multiple_continue_takes_last(self):
        output = "<!-- loop:done -->\n中間過程\n<!-- loop:continue -->"
        assert parse_loop_signal(output) == LoopSignal.CONTINUE

    def test_case_insensitive(self):
        output = "<!-- LOOP:CONTINUE -->"
        assert parse_loop_signal(output) == LoopSignal.CONTINUE

    def test_case_insensitive_done(self):
        output = "<!-- Loop:Done -->"
        assert parse_loop_signal(output) == LoopSignal.DONE

    def test_whitespace_in_tag(self):
        output = "<!--  loop:continue  -->"
        assert parse_loop_signal(output) == LoopSignal.CONTINUE

    def test_signal_in_middle_of_text(self):
        output = "前面的文字\n<!-- loop:continue -->\n後面的文字"
        assert parse_loop_signal(output) == LoopSignal.CONTINUE

    def test_similar_but_invalid_tag(self):
        output = "<!-- loop:restart -->"
        assert parse_loop_signal(output) == LoopSignal.NONE

    def test_incomplete_tag(self):
        output = "<!-- loop:continue"
        assert parse_loop_signal(output) == LoopSignal.NONE


# ========== build_next_round_prompt ==========

class TestBuildNextRoundPrompt:
    """組裝下一輪 prompt。"""

    def test_basic_format(self):
        result = build_next_round_prompt(
            original_prompt="修復 bug",
            previous_output="已修復 X",
            round_num=2,
            max_rounds=3,
        )
        assert "修復 bug" in result
        assert "Round 2/3" in result
        assert "Round 1" in result
        assert "已修復 X" in result

    def test_contains_original_prompt(self):
        result = build_next_round_prompt(
            original_prompt="原始任務描述",
            previous_output="output",
            round_num=2,
            max_rounds=5,
        )
        assert result.startswith("原始任務描述")

    def test_truncates_long_output(self):
        long_output = "x" * 5000
        result = build_next_round_prompt(
            original_prompt="task",
            previous_output=long_output,
            round_num=2,
            max_rounds=3,
        )
        assert "truncated" in result
        # 截取後長度應遠小於原始 5000
        assert len(result) < 5000

    def test_round_numbers_correct(self):
        result = build_next_round_prompt(
            original_prompt="task",
            previous_output="done",
            round_num=3,
            max_rounds=5,
        )
        assert "Round 3/5" in result
        assert "Round 2" in result

    def test_loop_instruction_present(self):
        result = build_next_round_prompt(
            original_prompt="task",
            previous_output="output",
            round_num=2,
            max_rounds=3,
        )
        assert "loop:done" in result
        assert "loop:continue" in result


# ========== max_rounds=1 向後相容 ==========

class TestBackwardsCompatibility:
    """max_rounds=1 時不觸發 loop（現有行為不變）。"""

    def test_single_round_no_loop_on_continue(self):
        """max_rounds=1 時，即使有 continue 信號也不應觸發 loop。
        此邏輯由 worker 層控制，這裡驗證 parse 本身仍正常辨識。"""
        output = "結果\n<!-- loop:continue -->"
        signal = parse_loop_signal(output)
        assert signal == LoopSignal.CONTINUE
        # worker 層會檢查 max_rounds > 1 才進入 loop

    def test_signal_enum_values(self):
        assert LoopSignal.CONTINUE.value == "continue"
        assert LoopSignal.DONE.value == "done"
        assert LoopSignal.NONE.value == "none"
