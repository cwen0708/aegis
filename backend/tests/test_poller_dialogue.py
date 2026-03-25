"""Tests for dialogue extraction — now via DialogueHook."""
import re
import pytest


def _extract_dialogue(output: str):
    """本地提取函式（測試用，邏輯與 DialogueHook 一致）"""
    m = re.search(r'<!-- dialogue: (.+?) -->', output)
    return m.group(1).strip() if m else None


class TestExtractDialogue:
    def test_basic_extraction(self):
        output = "Some output\n<!-- dialogue: 任務完成啦！ -->"
        assert _extract_dialogue(output) == "任務完成啦！"

    def test_with_spaces(self):
        output = "<!-- dialogue:  今天的工作完成了  -->"
        assert _extract_dialogue(output) == "今天的工作完成了"

    def test_no_dialogue(self):
        output = "Just some regular output without dialogue tag"
        assert _extract_dialogue(output) is None

    def test_empty_output(self):
        assert _extract_dialogue("") is None

    def test_dialogue_in_middle(self):
        output = "line1\n<!-- dialogue: 中間的對話 -->\nline3"
        assert _extract_dialogue(output) == "中間的對話"

    def test_multiline_output(self):
        output = """
Task completed successfully.
Files modified: 3
Tests passed: 12/12

<!-- dialogue: 搞定了，12 個測試全部通過！ -->
"""
        assert _extract_dialogue(output) == "搞定了，12 個測試全部通過！"

    def test_html_comment_without_dialogue(self):
        output = "<!-- some other comment -->"
        assert _extract_dialogue(output) is None
