"""Anthropic SDK 直接串流呼叫 — 用於 chat 路徑（取代 CLI subprocess）。"""
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, List

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


def resolve_model(name: str) -> str:
    """簡稱轉全名，已是全名則原樣回傳。"""
    return MODEL_MAP.get(name, name)


def stream_chat(
    system_prompt: str,
    messages: List[dict],
    model: str = "claude-haiku-4-5-20251001",
    api_key: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """用 Anthropic SDK 直接串流呼叫。

    Args:
        system_prompt: 系統提示（soul + skills + 安全限制）
        messages: 對話歷史 + 當前用戶訊息
        model: 模型全名或簡稱
        api_key: API key（None 則從環境變數讀取）
        on_text: 每個 text delta 的回呼
        max_tokens: 最大輸出 token 數

    Returns:
        {"status": "success"|"error", "output": str, "token_info": dict}
    """
    import anthropic

    model = resolve_model(model)
    kwargs = {"api_key": api_key} if api_key else {}
    client = anthropic.Anthropic(**kwargs)

    result_text: list[str] = []
    token_info: dict = {}

    try:
        with client.messages.stream(
            model=model,
            system=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = getattr(event.delta, "text", None)
                    if delta:
                        result_text.append(delta)
                        if on_text:
                            try:
                                on_text(delta)
                            except Exception:
                                pass

            final = stream.get_final_message()
            token_info = {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
                "model": model,
                "cache_read_tokens": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
            }

    except Exception as e:
        logger.error(f"[SDK-Chat] Error: {e}")
        return {
            "status": "error",
            "output": str(e),
            "token_info": {},
        }

    output = "".join(result_text)
    logger.info(f"[SDK-Chat] {model} in={token_info.get('input_tokens',0)} out={token_info.get('output_tokens',0)}")
    return {
        "status": "success",
        "output": output,
        "token_info": token_info,
    }
