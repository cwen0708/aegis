"""測試 stream-json 格式的 JSON 結構"""
import os
import time
import json
import re

# 清理環境變數
for key in list(os.environ.keys()):
    if key.upper().startswith(("CLAUDE", "ANTHROPIC")):
        del os.environ[key]

from winpty import PtyProcess

cmd = [
    "claude", "-p", "say hello",
    "--output-format", "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
    "--model", "haiku"
]

print(f"=== Testing stream-json structure ===\n")

start = time.time()
pty = PtyProcess.spawn(cmd)

buffer = ""
json_lines = []

while pty.isalive():
    try:
        chunk = pty.read(1024)
        if chunk:
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                # 清理 ANSI codes
                clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
                if clean.strip().startswith("{"):
                    json_lines.append(clean.strip())
    except EOFError:
        break

# 處理剩餘
for line in buffer.split("\n"):
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
    if clean.strip().startswith("{"):
        json_lines.append(clean.strip())

pty.wait()

print(f"Total JSON lines: {len(json_lines)}\n")

for i, line in enumerate(json_lines):
    try:
        data = json.loads(line)
        msg_type = data.get("type", "unknown")
        print(f"--- Line {i+1}: type={msg_type} ---")

        if msg_type == "assistant":
            # 檢查 delta
            delta = data.get("delta", {})
            if delta:
                print(f"  delta: {delta}")
            # 檢查 message.content
            msg = data.get("message", {})
            content = msg.get("content", [])
            if content:
                print(f"  content: {content[:2]}...")  # 只顯示前2個
        elif msg_type == "content_block_delta":
            delta = data.get("delta", {})
            print(f"  delta: {delta}")
        elif msg_type == "result":
            result = data.get("result", "")
            print(f"  result: {result[:100]}...")
        else:
            # 其他類型只顯示 keys
            print(f"  keys: {list(data.keys())[:5]}")
    except json.JSONDecodeError as e:
        print(f"--- Line {i+1}: PARSE ERROR: {e} ---")
        print(f"  raw: {line[:100]}...")

print(f"\n=== Done in {time.time()-start:.2f}s ===")
