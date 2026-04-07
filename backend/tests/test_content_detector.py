"""ContentDetectorHook — 輸出端敏感資料偵測 單元測試"""
import logging

from app.core.data_classifier import SecurityLevel
from app.hooks import StreamEvent, TaskContext
from app.hooks.content_detector import ContentDetectorHook, S3_WARNING_MARKER


class TestOnStreamS3:
    """on_stream: S3 等級偵測"""

    def test_detect_s3_in_stream(self, caplog):
        """含 API key 的串流事件應觸發 S3 error 告警"""
        hook = ContentDetectorHook()
        event = StreamEvent(
            kind="output",
            content="Here is the key: sk-ant-abcdef1234567890abcdef",
        )

        with caplog.at_level(logging.ERROR, logger="app.hooks.content_detector"):
            hook.on_stream(event)

        assert len(hook._detections) == 1
        assert hook._detections[0].level == SecurityLevel.S3
        assert hook._detections[0].pattern_name == "anthropic_api_key"
        assert "S3 hit in stream" in caplog.text

    def test_debounce_same_pattern(self, caplog):
        """同一 pattern 重複出現只告警一次"""
        hook = ContentDetectorHook()
        event1 = StreamEvent(kind="output", content="sk-ant-abcdef1234567890abcdef")
        event2 = StreamEvent(kind="output", content="sk-ant-zzzzzzzzzzzzzzzzzzzzzzz")

        with caplog.at_level(logging.ERROR, logger="app.hooks.content_detector"):
            hook.on_stream(event1)
            hook.on_stream(event2)

        # 兩筆偵測紀錄，但 log 只一次
        assert len(hook._detections) == 2
        assert caplog.text.count("S3 hit in stream") == 1


class TestOnStreamS2:
    """on_stream: S2 等級偵測"""

    def test_detect_s2_in_stream(self, caplog):
        """含 email 的串流事件應觸發 S2 warning 告警"""
        hook = ContentDetectorHook()
        event = StreamEvent(
            kind="output",
            content="Contact us at user@example.com for details",
        )

        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_stream(event)

        assert len(hook._detections) == 1
        assert hook._detections[0].level == SecurityLevel.S2
        assert hook._detections[0].pattern_name == "email"
        assert "S2 hit in stream" in caplog.text


class TestCleanStream:
    """on_stream: 無敏感資料"""

    def test_clean_stream_no_alert(self, caplog):
        """無敏感資料的串流事件不應產生告警"""
        hook = ContentDetectorHook()
        event = StreamEvent(
            kind="output",
            content="This is a normal response without any sensitive data.",
        )

        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_stream(event)

        assert len(hook._detections) == 0
        assert caplog.text == ""

    def test_empty_content_no_alert(self):
        """空內容不應觸發掃描"""
        hook = ContentDetectorHook()
        event = StreamEvent(kind="output", content="")

        hook.on_stream(event)

        assert len(hook._detections) == 0


class TestOnComplete:
    """on_complete: 最終全文掃描與彙總"""

    def test_on_complete_summary_with_s3(self, caplog):
        """有 S3 命中時應彙總並附加警告標記"""
        hook = ContentDetectorHook()
        ctx = TaskContext(
            output="Deploy key: sk-ant-abcdef1234567890abcdef\nEmail: test@example.com",
        )

        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_complete(ctx)

        # 偵測到 S3 + S2
        s3_detections = [d for d in hook._detections if d.level == SecurityLevel.S3]
        s2_detections = [d for d in hook._detections if d.level == SecurityLevel.S2]
        assert len(s3_detections) >= 1
        assert len(s2_detections) >= 1

        # output 末尾附加警告標記
        assert ctx.output.endswith(S3_WARNING_MARKER)
        assert "Output scan summary" in caplog.text

    def test_on_complete_s2_only_no_marker(self, caplog):
        """只有 S2 命中時不附加 S3 警告標記"""
        hook = ContentDetectorHook()
        ctx = TaskContext(
            output="Contact: test@example.com",
        )

        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_complete(ctx)

        assert len(hook._detections) >= 1
        assert not ctx.output.endswith(S3_WARNING_MARKER)
        assert "Output scan summary" in caplog.text

    def test_on_complete_clean_output(self, caplog):
        """乾淨輸出不產生偵測紀錄"""
        hook = ContentDetectorHook()
        ctx = TaskContext(output="All tasks completed successfully.")

        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_complete(ctx)

        assert len(hook._detections) == 0
        assert caplog.text == ""

    def test_on_complete_empty_output(self):
        """空 output 不觸發掃描"""
        hook = ContentDetectorHook()
        ctx = TaskContext(output="")

        hook.on_complete(ctx)

        assert len(hook._detections) == 0

    def test_stream_then_complete_dedup(self, caplog):
        """stream 階段已偵測的 pattern 不在 complete 階段重複記錄"""
        hook = ContentDetectorHook()

        # stream 階段先偵測到 API key
        event = StreamEvent(
            kind="output",
            content="sk-ant-abcdef1234567890abcdef",
        )
        hook.on_stream(event)
        assert len(hook._detections) == 1

        # complete 階段同樣的 output — 不應新增重複偵測
        ctx = TaskContext(output="sk-ant-abcdef1234567890abcdef")
        with caplog.at_level(logging.WARNING, logger="app.hooks.content_detector"):
            hook.on_complete(ctx)

        # 只有 stream 階段的 1 筆（complete 階段因 dedup 跳過）
        assert len(hook._detections) == 1
        # 但仍附加警告標記（因為有 S3）
        assert ctx.output.endswith(S3_WARNING_MARKER)
