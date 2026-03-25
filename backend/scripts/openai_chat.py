#!/usr/bin/env python3
"""
OpenAI CLI wrapper — 供 Aegis worker/runner 以 subprocess 方式呼叫。

用法：
    echo "你的 prompt" | python scripts/openai_chat.py [--model MODEL]

環境變數：
    OPENAI_API_KEY  必須設定

輸出：JSON 格式，包含 result_text、model、usage 等欄位，
      與 Aegis stream_parsers 的 parse_openai_json() 對應。
"""
import argparse
import json
import sys
import time
import os


def main():
    parser = argparse.ArgumentParser(description="OpenAI chat completion wrapper")
    parser.add_argument("--model", default="gpt-4o", help="模型名稱（預設 gpt-4o）")
    parser.add_argument("-p", "--prompt", default=None, help="Prompt 文字（未指定時從 stdin 讀取）")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(json.dumps({"error": "OPENAI_API_KEY not set"}), file=sys.stderr)
        sys.exit(1)

    # 延遲 import，讓缺套件時能先印出 help
    try:
        from openai import OpenAI
    except ImportError:
        print(json.dumps({"error": "openai package not installed"}), file=sys.stderr)
        sys.exit(1)

    prompt = args.prompt
    if prompt is None:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print(json.dumps({"error": "empty prompt"}), file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    start = time.time()

    response = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": prompt}],
    )

    duration_ms = int((time.time() - start) * 1000)
    choice = response.choices[0]
    usage = response.usage

    result = {
        "result_text": choice.message.content or "",
        "model": response.model,
        "duration_ms": duration_ms,
        "cost_usd": 0,  # 需要外部計算
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
