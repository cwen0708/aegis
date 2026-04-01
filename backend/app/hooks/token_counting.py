"""
Token Counting Hook — 記錄任務的 token 使用量和成本

在 on_complete 時：
- 從 token_info 提取 input/output tokens
- 計算成本（根據 model 和定價表）
- 累計寫入 CardIndex
"""
import logging
from sqlmodel import Session

from app.hooks import Hook, TaskContext
from app.database import engine
from app.models.core import CardIndex
from app.core.cost_calculator import calculate_cost

logger = logging.getLogger(__name__)


class TokenCountingHook(Hook):
    """追蹤每個任務的 token 使用量和成本"""

    def on_complete(self, ctx: TaskContext) -> None:
        """記錄 token 用量到 CardIndex"""
        if not ctx.token_info:
            return

        input_tokens = ctx.token_info.get("input_tokens", 0) or 0
        output_tokens = ctx.token_info.get("output_tokens", 0) or 0
        model = ctx.token_info.get("model", "") or ""

        if not model and ctx.provider:
            # fallback: 根據 provider 推斷模型
            if "claude" in ctx.provider.lower():
                model = "claude-haiku-4-5"
            elif "gemini" in ctx.provider.lower():
                model = "gemini-2.0-flash"

        cost = calculate_cost(model, input_tokens, output_tokens)

        # 更新 CardIndex 中的成本記錄
        try:
            with Session(engine) as session:
                card_idx = session.get(CardIndex, ctx.card_id)
                if card_idx:
                    card_idx.total_input_tokens += input_tokens
                    card_idx.total_output_tokens += output_tokens
                    card_idx.estimated_cost_usd += cost
                    session.add(card_idx)
                    session.commit()
                    logger.info(
                        f"[TokenCounting] Card {ctx.card_id}: "
                        f"input={input_tokens}, output={output_tokens}, "
                        f"cost=${cost:.4f} (cumulative: ${card_idx.estimated_cost_usd:.4f})"
                    )
        except Exception as e:
            logger.warning(f"[TokenCounting] Failed to record tokens for card {ctx.card_id}: {e}")
