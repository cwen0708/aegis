"""Ralph Loop — 多輪迭代引擎

AI 透過 HTML 註解標記控制迭代：
- <!-- loop:continue --> 要求繼續下一輪
- <!-- loop:done -->     明確表示完成

用於 review-and-fix 循環、漸進式開發等多輪場景。
"""
import re
from enum import Enum


class LoopSignal(Enum):
    """AI 輸出中的迭代控制信號。"""
    CONTINUE = "continue"
    DONE = "done"
    NONE = "none"


_LOOP_PATTERN = re.compile(r"<!--\s*loop:(continue|done)\s*-->", re.IGNORECASE)


def parse_loop_signal(output: str) -> LoopSignal:
    """偵測 AI 輸出中的 loop 信號。多個標記時取最後一個。

    Args:
        output: AI 的完整輸出文字

    Returns:
        LoopSignal: CONTINUE / DONE / NONE
    """
    matches = _LOOP_PATTERN.findall(output)
    if not matches:
        return LoopSignal.NONE
    last = matches[-1].lower()
    if last == "continue":
        return LoopSignal.CONTINUE
    return LoopSignal.DONE


def build_next_round_prompt(
    original_prompt: str,
    previous_output: str,
    round_num: int,
    max_rounds: int,
) -> str:
    """組裝下一輪的 prompt，包含前一輪結果摘要。

    Args:
        original_prompt: 原始任務 prompt
        previous_output: 上一輪 AI 輸出
        round_num: 即將執行的輪次（2-based）
        max_rounds: 最大允許輪次

    Returns:
        組裝好的下一輪 prompt
    """
    # 截取前一輪輸出摘要（避免 prompt 無限膨脹）
    summary = previous_output.strip()
    if len(summary) > 2000:
        summary = summary[:2000] + "\n... (truncated)"

    return (
        f"{original_prompt}\n\n"
        f"---\n\n"
        f"## Ralph Loop — Round {round_num}/{max_rounds}\n\n"
        f"以下是上一輪（Round {round_num - 1}）的執行結果：\n\n"
        f"```\n{summary}\n```\n\n"
        f"請基於上一輪結果繼續執行。"
        f"完成後使用 `<!-- loop:done -->` 標記，"
        f"或使用 `<!-- loop:continue -->` 繼續下一輪。"
    )
