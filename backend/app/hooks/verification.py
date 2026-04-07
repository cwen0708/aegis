"""
VerificationHook — Anti-fabrication 驗證 Hook

在任務完成後（on_complete）執行所有驗證器，
偵測 AI 成員是否捏造輸出結果。
"""
import logging

from app.core.verification import VerifiedRegistry, create_default_registry
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)


class VerificationHook(Hook):
    """POST Hook — 任務完成後執行 anti-fabrication 驗證"""

    def __init__(self, registry: VerifiedRegistry | None = None) -> None:
        self._registry = registry or create_default_registry()

    def on_complete(self, ctx: TaskContext) -> None:
        results = self._registry.run_all(ctx)
        for r in results:
            if not r.passed:
                logger.warning(
                    "[Verification] FAILED — %s: %s (%s)",
                    r.verifier_name,
                    r.evidence,
                    r.details,
                )
