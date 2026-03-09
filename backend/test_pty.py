"""測試 PTY 即時輸出"""
import os
import sys
import time

# 移除 CLAUDE 相關環境變數
claude_env_keys = [k for k in os.environ.keys() if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
for key in claude_env_keys:
    del os.environ[key]
    print(f"Removed env: {key}")

os.environ["CLAUDE_CODE_ENTRY_POINT"] = "worker"

from winpty import PtyProcess

cmd = ["claude", "-p", "說 hello", "--dangerously-skip-permissions", "--model", "haiku"]

print(f"\n=== Starting PTY with: {' '.join(cmd[:3])}... ===")
print(f"CWD: {os.getcwd()}")
start = time.time()

pty = PtyProcess.spawn(cmd)

line_count = 0
while pty.isalive():
    try:
        line = pty.readline()
        if line:
            line_count += 1
            elapsed = time.time() - start
            print(f"[{elapsed:.2f}s] LINE {line_count}: {line.rstrip()[:100]}")
    except EOFError:
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(0.1)

# 讀取剩餘
try:
    while True:
        line = pty.readline()
        if not line:
            break
        line_count += 1
        elapsed = time.time() - start
        print(f"[{elapsed:.2f}s] LINE {line_count}: {line.rstrip()[:100]}")
except EOFError:
    pass

pty.wait()
print(f"\n=== Done. Exit code: {pty.exitstatus}, Total lines: {line_count}, Time: {time.time()-start:.2f}s ===")
