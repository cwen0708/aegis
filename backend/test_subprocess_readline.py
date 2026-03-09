"""測試 subprocess + readline 即時讀取（類似 Happy 的做法）"""
import os
import subprocess
import time
import json
import re

# 清理環境變數
env = os.environ.copy()
claude_keys = [k for k in env.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
for key in claude_keys:
    del env[key]
env["CLAUDE_CODE_ENTRYPOINT"] = "sdk"

cmd = [
    "claude", "-p", "count from 1 to 3, one per line",
    "--output-format", "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
    "--model", "haiku"
]

print(f"=== Testing subprocess readline (like Happy) ===\n")

start = time.time()

# 用 subprocess + shell=True（類似 Node.js spawn with shell: true）
proc = subprocess.Popen(
    " ".join(cmd),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    bufsize=0,  # unbuffered
    encoding='utf-8',
    errors='replace',
    shell=True
)

# 逐行讀取
for line in proc.stdout:
    elapsed = time.time() - start
    line = line.strip()
    if not line:
        continue

    # 嘗試解析 JSON
    if line.startswith("{"):
        try:
            data = json.loads(line)
            msg_type = data.get("type", "?")

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
            print(f"[{elapsed:5.2f}s] RAW: {line[:60]}")
    else:
        print(f"[{elapsed:5.2f}s] RAW: {line[:60]}")

proc.wait()
print(f"\n=== Done in {time.time()-start:.2f}s, exit={proc.returncode} ===")
