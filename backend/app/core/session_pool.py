"""Process Pool — 持久 Claude CLI 進程池（node cli.js + stdin pipe 多輪對話）。

用 node cli.js 直接啟動（繞過 shell wrapper 和 TUI），
stdin 寫 JSON 行，stdout 讀 stream-json，進程不 close stdin。

用法：
    from app.core.session_pool import process_pool

    result = process_pool.send_message(
        chat_key="telegram:123:xiao-yin",
        message="你好",
        model="haiku",
        member_id=4,
        auth_info={"auth_type": "cli", "oauth_token": "..."},
    )
"""
import json
import os
import subprocess
import threading
import time
import logging
import shutil
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

PROCESS_TTL = 1800  # 30 分鐘
CLEANUP_INTERVAL = 60

# 找 Claude Code cli.js 路徑（啟動時解析一次）
_CLI_JS_PATH: Optional[str] = None


def _find_cli_js() -> Optional[str]:
    """找 Claude Code 的 cli.js 路徑。"""
    candidates = [
        "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        Path(os.path.expanduser("~")) / ".local" / "lib" / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js",
    ]
    # 也從 which claude 反推
    claude_bin = shutil.which("claude")
    if claude_bin:
        real = Path(claude_bin).resolve()
        # /usr/bin/claude → /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js
        guess = real.parent.parent / "lib" / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        candidates.insert(0, guess)

    for p in candidates:
        if Path(p).exists():
            return str(p)
    return None


def _get_cli_js() -> str:
    """取得 cli.js 路徑，找不到則 fallback 到 claude 命令。"""
    global _CLI_JS_PATH
    if _CLI_JS_PATH is None:
        _CLI_JS_PATH = _find_cli_js() or ""
    return _CLI_JS_PATH


@dataclass
class ProcessEntry:
    proc: subprocess.Popen
    chat_key: str
    model: str = ""
    session_id: str = ""
    last_active: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ProcessPool:
    """持久 Claude CLI 進程池（node cli.js 模式）。"""

    def __init__(self, ttl: int = PROCESS_TTL):
        self._entries: dict[str, ProcessEntry] = {}
        self._pool_lock = threading.Lock()
        self._ttl = ttl
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def send_message(
        self,
        chat_key: str,
        message: str,
        model: str = "haiku",
        member_id: Optional[int] = None,
        auth_info: Optional[Dict[str, str]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """送訊息到持久進程。沒有進程或已死則自動 spawn。"""
        entry = self._get_or_spawn(chat_key, model, member_id, auth_info, extra_env)

        with entry.lock:
            if entry.proc.poll() is not None:
                logger.warning(f"[ProcessPool] Dead process for {chat_key}, respawning")
                self._remove(chat_key)
                entry = self._get_or_spawn(chat_key, model, member_id, auth_info, extra_env)

            try:
                return self._send_and_read(entry, message, on_line)
            except Exception as e:
                logger.error(f"[ProcessPool] Error for {chat_key}: {e}")
                self._kill_entry(entry)
                self._remove(chat_key)
                return {"status": "error", "output": str(e), "token_info": {}}

    def kill(self, chat_key: str):
        with self._pool_lock:
            entry = self._entries.pop(chat_key, None)
        if entry:
            self._kill_entry(entry)
            logger.info(f"[ProcessPool] Killed {chat_key}")

    def active_count(self) -> int:
        with self._pool_lock:
            return len(self._entries)

    # 向後相容（worker.py --resume 路徑）
    def get_or_create(self, chat_id: str):
        with self._pool_lock:
            entry = self._entries.get(chat_id)
            if entry and entry.proc.poll() is None and entry.session_id:
                return entry.session_id, False
        return None, True

    def register(self, chat_id: str, session_id: str):
        pass

    # ── 內部方法 ──

    def _get_or_spawn(self, chat_key, model, member_id, auth_info, extra_env) -> ProcessEntry:
        with self._pool_lock:
            entry = self._entries.get(chat_key)
            if entry and entry.proc.poll() is None:
                return entry

        entry = self._spawn(chat_key, model, member_id, auth_info, extra_env)
        with self._pool_lock:
            existing = self._entries.get(chat_key)
            if existing and existing.proc.poll() is None:
                self._kill_entry(entry)
                return existing
            self._entries[chat_key] = entry
        return entry

    def _spawn(self, chat_key, model, member_id, auth_info, extra_env) -> ProcessEntry:
        """用 node cli.js 啟動持久 Claude CLI 進程。"""
        cli_js = _get_cli_js()

        if cli_js:
            cmd = ["node", "--no-warnings", cli_js]
        else:
            cmd = ["claude"]
            logger.warning("[ProcessPool] cli.js not found, falling back to claude command")

        logger.info(f"[ProcessPool] cli_js={cli_js or 'NOT FOUND'}")

        cmd.extend([
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model or "haiku",
        ])

        if member_id:
            mcp_path = self._get_mcp_config(member_id)
            if mcp_path:
                cmd.extend(["--mcp-config", mcp_path])

        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        env["CLAUDE_CODE_ENTRYPOINT"] = "sdk"

        auth_info = auth_info or {}
        if auth_info.get("api_key"):
            env["ANTHROPIC_API_KEY"] = auth_info["api_key"]
        elif auth_info.get("oauth_token"):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_info["oauth_token"]

        if extra_env:
            env.update(extra_env)

        logger.info(f"[ProcessPool] Spawning: {' '.join(cmd[:5])}... for {chat_key}")
        logger.info(f"[ProcessPool] ENV keys: {sorted([k for k in env if 'CLAUDE' in k or 'ANTHROPIC' in k or 'PATH' in k or 'NODE' in k])}")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

        entry = ProcessEntry(proc=proc, chat_key=chat_key, model=model)
        self._read_init(entry)
        return entry

    def _read_init(self, entry: ProcessEntry):
        """讀掉 init/system 行。"""
        deadline = time.time() + 20
        while time.time() < deadline:
            if entry.proc.poll() is not None:
                # 讀 stderr 看為什麼死了
                stderr = ""
                try:
                    stderr = entry.proc.stderr.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                logger.warning(f"[ProcessPool] Process died (rc={entry.proc.returncode}) for {entry.chat_key}: {stderr}")
                break
            raw = entry.proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "system":
                    entry.session_id = data.get("session_id", "")
                    logger.info(f"[ProcessPool] Init OK session={entry.session_id[:12]} for {entry.chat_key}")
                    return
            except json.JSONDecodeError:
                continue
        logger.warning(f"[ProcessPool] Init timeout for {entry.chat_key}")

    def _send_and_read(self, entry: ProcessEntry, message: str, on_line=None) -> Dict[str, Any]:
        """送 user message + 讀到 result 行。"""
        msg = {"type": "user", "message": {"role": "user", "content": message}}
        payload = json.dumps(msg, ensure_ascii=False) + "\n"
        entry.proc.stdin.write(payload.encode("utf-8"))
        entry.proc.stdin.flush()
        entry.last_active = time.time()
        logger.info(f"[ProcessPool] Sent to {entry.chat_key} ({len(message)} chars)")

        return self._read_until_result(entry, on_line)

    def _read_until_result(self, entry: ProcessEntry, on_line=None) -> Dict[str, Any]:
        """讀 stdout 直到 result 行。"""
        from app.core.stream_parsers import parse_stream_json_text, parse_stream_json_tokens

        result_text_parts = []
        token_info = {}

        while True:
            raw = entry.proc.stdout.readline()
            if not raw:
                logger.warning(f"[ProcessPool] EOF for {entry.chat_key}")
                return {
                    "status": "error",
                    "output": "".join(result_text_parts) or "Process exited",
                    "token_info": token_info,
                }

            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("{"):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass

            if msg_type == "assistant":
                text = parse_stream_json_text(line)
                if text:
                    result_text_parts.append(text)

            if msg_type == "result":
                token_info = parse_stream_json_tokens(line)
                entry.session_id = token_info.get("session_id") or entry.session_id
                entry.last_active = time.time()
                return {
                    "status": "success",
                    "output": "".join(result_text_parts),
                    "token_info": token_info,
                    "session_id": entry.session_id,
                }

    def _get_mcp_config(self, member_id: int) -> Optional[str]:
        try:
            from app.database import engine
            from sqlmodel import Session, select
            from app.models.core import Member
            from app.core.member_profile import get_member_dir
            with Session(engine) as session:
                member = session.get(Member, member_id)
                if member and member.slug:
                    mcp_path = get_member_dir(member.slug) / "mcp.json"
                    if mcp_path.exists():
                        return str(mcp_path)
        except Exception:
            pass
        return None

    def _remove(self, chat_key: str):
        with self._pool_lock:
            self._entries.pop(chat_key, None)

    def _kill_entry(self, entry: ProcessEntry):
        try:
            if entry.proc.poll() is None:
                entry.proc.stdin.close()
                entry.proc.kill()
                entry.proc.wait(timeout=5)
        except Exception:
            pass

    def _cleanup_loop(self):
        while True:
            time.sleep(CLEANUP_INTERVAL)
            try:
                now = time.time()
                with self._pool_lock:
                    expired = [k for k, v in self._entries.items()
                               if now - v.last_active > self._ttl or v.proc.poll() is not None]
                for key in expired:
                    with self._pool_lock:
                        entry = self._entries.pop(key, None)
                    if entry:
                        self._kill_entry(entry)
                        logger.info(f"[ProcessPool] Cleaned {key}")
            except Exception as e:
                logger.warning(f"[ProcessPool] Cleanup error: {e}")


# 全域 singleton
process_pool = ProcessPool()
session_pool = process_pool
