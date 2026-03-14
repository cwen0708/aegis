"""
Web Terminal — WebSocket-based PTY terminal for Aegis dashboard.

Provides a browser-based terminal (via xterm.js) that spawns a local shell.
Used for server management, Claude workspace trust, log inspection, etc.
"""
import asyncio
import logging
import os
import platform
import struct

logger = logging.getLogger(__name__)


async def terminal_handler(websocket):
    """Handle a WebSocket terminal session.

    Protocol:
    - Client sends JSON: {"type": "input", "data": "..."} for keystrokes
    - Client sends JSON: {"type": "resize", "cols": N, "rows": N}
    - Server sends JSON: {"type": "output", "data": "..."} for terminal output
    """
    import json

    system = platform.system()

    if system == "Windows":
        await _handle_windows(websocket)
    else:
        await _handle_unix(websocket)


async def _handle_unix(websocket):
    """Unix PTY terminal via pty.fork()."""
    import pty
    import fcntl
    import termios
    import signal
    import json

    # Fork a PTY
    pid, fd = pty.fork()

    if pid == 0:
        # Child process — exec shell
        shell = os.environ.get("SHELL", "/bin/bash")
        os.execvp(shell, [shell, "--login"])
        return

    # Parent process
    # Make fd non-blocking
    import select as _select

    try:
        # Send initial output
        await websocket.send_json({"type": "output", "data": ""})

        async def read_pty():
            """Read from PTY and send to WebSocket."""
            loop = asyncio.get_event_loop()
            while True:
                try:
                    # Use thread to avoid blocking event loop
                    data = await loop.run_in_executor(
                        None, lambda: os.read(fd, 4096)
                    )
                    if not data:
                        break
                    await websocket.send_json({
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace"),
                    })
                except OSError:
                    break
                except Exception as e:
                    logger.warning(f"[Terminal] PTY read error: {e}")
                    break

        async def write_pty():
            """Read from WebSocket and write to PTY."""
            while True:
                try:
                    msg = await websocket.receive_json()
                    msg_type = msg.get("type")

                    if msg_type == "input":
                        data = msg.get("data", "")
                        os.write(fd, data.encode("utf-8"))

                    elif msg_type == "resize":
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

                except Exception:
                    break

        # Run both tasks concurrently
        reader = asyncio.create_task(read_pty())
        writer = asyncio.create_task(write_pty())

        done, pending = await asyncio.wait(
            [reader, writer],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    finally:
        # Cleanup
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass
        logger.info("[Terminal] Session ended")


async def _handle_windows(websocket):
    """Windows terminal via subprocess (no PTY, basic line mode)."""
    import json

    proc = await asyncio.create_subprocess_exec(
        "cmd.exe",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        async def read_proc():
            while True:
                try:
                    data = await proc.stdout.read(4096)
                    if not data:
                        break
                    await websocket.send_json({
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace"),
                    })
                except Exception:
                    break

        async def write_proc():
            while True:
                try:
                    msg = await websocket.receive_json()
                    if msg.get("type") == "input":
                        data = msg.get("data", "")
                        proc.stdin.write(data.encode("utf-8"))
                        await proc.stdin.drain()
                except Exception:
                    break

        reader = asyncio.create_task(read_proc())
        writer = asyncio.create_task(write_proc())

        done, pending = await asyncio.wait(
            [reader, writer],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    finally:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        logger.info("[Terminal] Windows session ended")
