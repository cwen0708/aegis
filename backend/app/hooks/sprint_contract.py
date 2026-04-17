"""SprintContractHook — 任務完成時驗證 acceptance_criteria 並記錄結構化摘要"""
import logging
import re
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)

# bullet 符號正則：- * • ✓ ☐ 數字. 等
_BULLET_RE = re.compile(r"^\s*(?:[-*•✓☐]\s*|\d+[.)]\s*)")


class SprintContractHook(Hook):
    """任務完成後逐條驗證 acceptance_criteria，輸出結構化 pass/fail 摘要。"""

    # ── 公開介面 ──

    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.acceptance_criteria:
            return

        criteria = _parse_criteria(ctx.acceptance_criteria)
        if not criteria:
            logger.info(
                "[SprintContract] Card %d — acceptance_criteria 無法拆解為條目，跳過驗證",
                ctx.card_id,
            )
            return

        results = _check_criteria(criteria, ctx.output)

        passed = sum(1 for _, ok in results if ok)
        total = len(results)
        all_pass = passed == total

        # 結構化摘要
        verdict = "PASS" if all_pass else "FAIL"
        lines = [f"[SprintContract] Card {ctx.card_id} — {verdict} ({passed}/{total})"]
        for item, ok in results:
            mark = "✓" if ok else "✗"
            lines.append(f"  {mark} {item}")

        log_msg = "\n".join(lines)
        if all_pass:
            logger.info(log_msg)
        else:
            logger.warning(log_msg)


# ── 內部工具函式 ──

def _parse_criteria(text: str) -> list[str]:
    """將 acceptance_criteria 文字依換行 + bullet 符號拆成條目列表。

    支援格式：
        - 條目一
        * 條目二
        1. 條目三
        純文字行（無 bullet 也視為一條）
    空行與純空白行會被忽略。
    """
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 去除 bullet 前綴
        cleaned = _BULLET_RE.sub("", line).strip()
        if cleaned:
            items.append(cleaned)
    return items


def _check_criteria(
    items: list[str], output: str
) -> list[tuple[str, bool]]:
    """逐條比對 output 是否涵蓋每個 criteria 條目。

    比對策略：將條目拆成關鍵詞，全部出現在 output 中即視為通過。
    關鍵詞以空白分割，忽略長度 ≤ 1 的 token（避免雜訊）。
    """
    output_lower = output.lower()
    results: list[tuple[str, bool]] = []
    for item in items:
        keywords = [w for w in item.lower().split() if len(w) > 1]
        if not keywords:
            # 條目全是短字元，視為通過（避免誤判）
            results.append((item, True))
            continue
        matched = all(kw in output_lower for kw in keywords)
        results.append((item, matched))
    return results
