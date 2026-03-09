"""測試 Claude CLI stream-json 輸出格式"""
import os
import time

# 清理環境變數
for key in list(os.environ.keys()):
    if key.upper().startswith(("CLAUDE", "ANTHROPIC")):
        del os.environ[key]

from winpty import PtyProcess

cmd = [
    "claude", "-p", "count from 1 to 5, one number per line",
    "--output-format", "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
    "--model", "haiku"
]

print(f"=== Testing stream-json ===")
print(f"Command: {' '.join(cmd[:5])}...")

start = time.time()
pty = PtyProcess.spawn(cmd)

while pty.isalive():
    try:
        chunk = pty.read(200)
        if chunk:
            elapsed = time.time() - start
            # 只顯示可讀字符
            clean = ''.join(c for c in chunk if c.isprintable() or c in '\n\r')
            if clean.strip():
                print(f"[{elapsed:.2f}s] {clean[:100]}")
    except EOFError:
        break

pty.wait()
print(f"\n=== Done in {time.time()-start:.2f}s, exit={pty.exitstatus} ===")
