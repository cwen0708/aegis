#!/usr/bin/env python3
"""
OpenAI SSE 串流適配器 — 將 OpenAI streaming response 轉換為 Aegis stream-json 格式。

用法：
    echo "你的 prompt" | python backend/scripts/openai_stream_chat.py [--model MODEL]
    python backend/scripts/openai_stream_chat.py -p "你的 prompt" [--model MODEL]

環境變數：
    OPENAI_API_KEY  必須設定

輸出：stream-json 格式（每行一個 JSON），與 Claude CLI --output-format stream-json 相容。
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
    {"type": "result", "usage": {...}, "result": "完整文字", ...}

Day 3 實作 — 獨立於 openai_chat.py（non-streaming），供 stream_json 模式使用。
"""
import argparse
import json
import sys
import time
import os


def _emit(obj: dict) -> None:
    """輸出一行 stream-json JSON。"""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _make_assistant_text(text: str) -> dict:
    """組裝 assistant 文字事件（與 Claude stream-json 格式一致）。"""
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def _make_result(full_text: str, model: str, usage: dict, duration_ms: int) -> dict:
    """組裝 result 事件（與 Claude stream-json 格式一致）。"""
    return {
        "type": "result",
        "result": full_text,
        "duration_ms": duration_ms,
        "total_cost_usd": 0,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
        "modelUsage": {
            model: {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        },
    }


def stream_openai_chat(prompt: str, model: str = "gpt-4o") -> None:
    """執行 OpenAI streaming chat completion，輸出 stream-json 行。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(json.dumps({"error": "OPENAI_API_KEY not set"}), file=sys.stderr)
        sys.exit(1)

    try:
        from openai import OpenAI
    except ImportError:
        print(json.dumps({"error": "openai package not installed"}), file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    start = time.time()

    # 累積完整文字
    text_parts: list[str] = []
    final_usage: dict = {}

    # 使用 stream_options 來取得最終 usage（OpenAI API 支援）
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        stream_options={"include_usage": True},
    )

    for chunk in response:
        # 最後一個 chunk（usage-only）：choices 為空
        if not chunk.choices:
            if chunk.usage:
                final_usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }
            continue

        choice = chunk.choices[0]
        delta = choice.delta

        # 提取文字增量
        if delta and delta.content:
            text = delta.content
            text_parts.append(text)
            _emit(_make_assistant_text(text))

    # 組裝完整文字
    full_text = "".join(text_parts)
    duration_ms = int((time.time() - start) * 1000)
    resolved_model = chunk.model if chunk else model

    # 發出 result 行
    _emit(_make_result(full_text, resolved_model, final_usage, duration_ms))


def main():
    parser = argparse.ArgumentParser(
        description="OpenAI streaming chat — stream-json output"
    )
    parser.add_argument("--model", default="gpt-4o", help="模型名稱（預設 gpt-4o）")
    parser.add_argument(
        "-p", "--prompt", default=None, help="Prompt 文字（未指定時從 stdin 讀取）"
    )
    args = parser.parse_args()

    prompt = args.prompt
    if prompt is None:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print(json.dumps({"error": "empty prompt"}), file=sys.stderr)
        sys.exit(1)

    stream_openai_chat(prompt, args.model)


if __name__ == "__main__":
    main()
