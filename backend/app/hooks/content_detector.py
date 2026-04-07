"""
ContentDetectorHook — AI 輸出端敏感資料即時偵測

在串流階段（on_stream）逐行掃描 AI 輸出，
在完成階段（on_complete）做最終全文掃描並彙總結果。

偵測等級：
- S2 命中 → logger.warning
- S3 命中 → logger.error + output 末尾附加警告標記
"""
import logging
from dataclasses import dataclass, field

from app.core.data_classifier import SecurityLevel, scan, Match
from app.hooks import Hook, StreamEvent, TaskContext

logger = logging.getLogger(__name__)

# S3 命中時附加到 output 末尾的警告標記
S3_WARNING_MARKER = "\n\n<!-- warning: S3 sensitive data detected in output -->"


@dataclass
class Detection:
    """單筆偵測紀錄"""
    pattern_name: str
    level: SecurityLevel
    matched: str
    phase: str  # "stream" | "complete"


class ContentDetectorHook(Hook):
    """AI 輸出端敏感資料偵測 Hook"""

    def __init__(self) -> None:
        self._detections: list[Detection] = []
        self._seen_patterns: set[str] = set()  # debounce: 已告警的 pattern_name

    def on_stream(self, event: StreamEvent) -> None:
        """DURING — 掃描每行串流輸出中的敏感資料"""
        if not event.content:
            return

        matches = scan(event.content)
        for m in matches:
            detection = Detection(
                pattern_name=m.pattern_name,
                level=m.level,
                matched=m.matched,
                phase="stream",
            )
            self._detections.append(detection)

            # debounce: 同一 pattern 只告警一次
            if m.pattern_name in self._seen_patterns:
                continue
            self._seen_patterns.add(m.pattern_name)

            if m.level == SecurityLevel.S3:
                logger.error(
                    "[ContentDetector] S3 hit in stream: %s",
                    m.pattern_name,
                )
            elif m.level == SecurityLevel.S2:
                logger.warning(
                    "[ContentDetector] S2 hit in stream: %s",
                    m.pattern_name,
                )

    def on_complete(self, ctx: TaskContext) -> None:
        """POST — 對完整輸出做最終掃描並彙總"""
        if not ctx.output:
            return

        matches = scan(ctx.output)
        for m in matches:
            # 避免與 stream 階段重複記錄同一 pattern
            if m.pattern_name not in self._seen_patterns:
                self._detections.append(Detection(
                    pattern_name=m.pattern_name,
                    level=m.level,
                    matched=m.matched,
                    phase="complete",
                ))

        if not self._detections:
            return

        # 彙總偵測結果
        s3_names = sorted({
            d.pattern_name for d in self._detections
            if d.level == SecurityLevel.S3
        })
        s2_names = sorted({
            d.pattern_name for d in self._detections
            if d.level == SecurityLevel.S2
        })

        summary_parts = []
        if s3_names:
            summary_parts.append(f"S3={s3_names}")
        if s2_names:
            summary_parts.append(f"S2={s2_names}")

        logger.warning(
            "[ContentDetector] Output scan summary: %s (total=%d detections)",
            ", ".join(summary_parts),
            len(self._detections),
        )

        # S3 命中：在 output 末尾附加警告標記
        if s3_names:
            ctx.output = ctx.output + S3_WARNING_MARKER
