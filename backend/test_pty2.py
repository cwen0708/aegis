"""測試 PTY 用 read() 而非 readline()"""
import os
import sys
import time

# 移除 CLAUDE 相關環境變數
claude_env_keys = [k for k in os.environ.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
for key in claude_env_keys:
    del os.environ[key]

os.environ["CLAUDE_CODE_ENTRY_POINT"] = "worker"

from winpty import PtyProcess

# 先測試一個會即時輸出的命令
print("=== Test 1: ping (should stream) ===")
pty = PtyProcess.spawn(["ping", "-n", "3", "127.0.0.1"])
start = time.time()
while pty.isalive():
    try:
        data = pty.read(100)  # 讀取最多 100 bytes
        if data:
            elapsed = time.time() - start
            print(f"[{elapsed:.2f}s] {repr(data[:80])}")
    except EOFError:
        break
pty.wait()
print(f"Ping done in {time.time()-start:.2f}s\n")

# 再測試 Claude
print("=== Test 2: claude (check streaming) ===")
cmd = ["claude", "-p", "just say hi", "--dangerously-skip-permissions", "--model", "haiku"]
pty2 = PtyProcess.spawn(cmd)
start = time.time()
chunks = []
while pty2.isalive():
    try:
        data = pty2.read(200)
        if data:
            elapsed = time.time() - start
            chunks.append((elapsed, data))
            print(f"[{elapsed:.2f}s] CHUNK: {len(data)} bytes")
    except EOFError:
        break
# 讀取剩餘
try:
    while True:
        data = pty2.read(200)
        if not data:
            break
        elapsed = time.time() - start
        chunks.append((elapsed, data))
        print(f"[{elapsed:.2f}s] CHUNK: {len(data)} bytes")
except EOFError:
    pass
pty2.wait()
print(f"\nClaude done in {time.time()-start:.2f}s, {len(chunks)} chunks")
print(f"Exit code: {pty2.exitstatus}")
