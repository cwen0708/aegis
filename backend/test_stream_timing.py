"""測試 stream-json 即時性"""
import os
import time
import json
import re

for key in list(os.environ.keys()):
    if key.upper().startswith(("CLAUDE", "ANTHROPIC")):
        del os.environ[key]

from winpty import PtyProcess

# 用一個需要多步驟輸出的任務
cmd = [
    "claude", "-p", "count from 1 to 5 slowly, one number per line with explanation",
    "--output-format", "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
    "--model", "haiku"
]

print(f"=== Testing stream-json timing ===\n")

start = time.time()
pty = PtyProcess.spawn(cmd)

buffer = ""

while pty.isalive():
    try:
        chunk = pty.read(512)
        if chunk:
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?', '', line)
                if clean.strip().startswith("{"):
                    try:
                        data = json.loads(clean.strip())
                        msg_type = data.get("type", "?")
                        elapsed = time.time() - start

                        if msg_type == "assistant":
                            content = data.get("content", [])
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")[:60]
                                    print(f"[{elapsed:5.2f}s] TEXT: {text}")
                        elif msg_type == "result":
                            result = data.get("result", "")[:60]
                            print(f"[{elapsed:5.2f}s] RESULT: {result}")
                        else:
                            print(f"[{elapsed:5.2f}s] {msg_type}")
                    except json.JSONDecodeError:
                        pass
    except EOFError:
        break

pty.wait()
print(f"\n=== Done in {time.time()-start:.2f}s ===")
