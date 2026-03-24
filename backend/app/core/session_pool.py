"""Process Pool — 持久 Claude CLI 進程池。

每個 chat_key 對應一個活著的 Claude 進程（stdin pipe 不 close），
30 分鐘無活動才 kill。第二條訊息零冷啟。

用法：
    from app.core.session_pool import process_pool

    result = process_pool.send_message(
        chat_key="telegram:123:xiao-yin",
        message="你好",
        model="haiku",
        member_id=4,
        auth_info={"auth_type": "cli", "oauth_token": "..."},
        on_line=lambda line: print(line),
    )
"""
import json
import os
import subprocess
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)

PROCESS_TTL = 1800  # 30 分鐘
CLEANUP_INTERVAL = 60  # 每 60 秒檢查


@dataclass
class ProcessEntry:
    proc: subprocess.Popen
    chat_key: str
    model: str = ""
    session_id: str = ""
    last_active: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ProcessPool:
    """持久 Claude CLI 進程池。"""

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
        """送訊息到持久進程。沒有進程或進程已死則自動 spawn。"""
        entry = self._get_or_spawn(chat_key, model, member_id, auth_info, extra_env)

        with entry.lock:  # 防止同一進程並發寫入
            # 檢查進程是否還活著
            if entry.proc.poll() is not None:
                logger.warning(f"[ProcessPool] Process dead for {chat_key}, respawning")
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
        """手動殺進程（如用戶要求重置對話）。"""
        with self._pool_lock:
            entry = self._entries.pop(chat_key, None)
        if entry:
            self._kill_entry(entry)
            logger.info(f"[ProcessPool] Killed process for {chat_key}")

    def active_count(self) -> int:
        with self._pool_lock:
            return len(self._entries)

    # ── 內部方法 ──

    def _get_or_spawn(self, chat_key, model, member_id, auth_info, extra_env) -> ProcessEntry:
        with self._pool_lock:
            entry = self._entries.get(chat_key)
            if entry and entry.proc.poll() is None:
                return entry

        # 不在 pool_lock 裡 spawn（避免長時間持鎖）
        entry = self._spawn(chat_key, model, member_id, auth_info, extra_env)
        with self._pool_lock:
            # 可能有並發 spawn，取先到的
            existing = self._entries.get(chat_key)
            if existing and existing.proc.poll() is None:
                self._kill_entry(entry)
                return existing
            self._entries[chat_key] = entry
        return entry

    def _spawn(self, chat_key, model, member_id, auth_info, extra_env) -> ProcessEntry:
        """啟動新的 Claude CLI 持久進程。"""
        cmd = [
            "claude",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model or "haiku",
        ]

        # MCP 注入
        if member_id:
            mcp_path = self._get_mcp_config(member_id)
            if mcp_path:
                cmd.extend(["--mcp-config", mcp_path])

        # 環境隔離
        from app.core.sandbox import build_sanitized_env, get_popen_kwargs
        env = build_sanitized_env()

        # 注入認證
        auth_info = auth_info or {}
        if auth_info.get("api_key"):
            env["ANTHROPIC_API_KEY"] = auth_info["api_key"]
        elif auth_info.get("oauth_token"):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_info["oauth_token"]

        # 注入額外環境變數（MCP AD 等）
        if extra_env:
            env.update(extra_env)

        popen_kwargs = get_popen_kwargs()
        logger.info(f"[ProcessPool] Spawning: {' '.join(cmd[:6])}... for {chat_key}")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **popen_kwargs,
        )

        entry = ProcessEntry(proc=proc, chat_key=chat_key, model=model)

        # 讀掉 init 行（system type）
        self._read_init(entry)

        return entry

    def _read_init(self, entry: ProcessEntry):
        """讀掉 spawn 後的 init 行（system/rate_limit 等），不阻塞。"""
        import select
        deadline = time.time() + 10  # 最多等 10 秒
        while time.time() < deadline:
            # 檢查 stdout 是否有資料
            if entry.proc.poll() is not None:
                break
            try:
                line = entry.proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded or not decoded.startswith("{"):
                    continue
                data = json.loads(decoded)
                t = data.get("type", "")
                if t == "system":
                    sid = data.get("session_id", "")
                    entry.session_id = sid
                    logger.info(f"[ProcessPool] Init OK, session={sid[:12]}")
                    return  # init 完成
                elif t == "rate_limit_event":
                    continue  # 跳過
                else:
                    # 非預期行，可能已經是回應了
                    break
            except Exception:
                break

    def _send_and_read(self, entry: ProcessEntry, message: str, on_line=None) -> Dict[str, Any]:
        """送訊息 + 讀到 result 行。"""
        msg = {"type": "user", "message": {"role": "user", "content": message}}
        payload = json.dumps(msg, ensure_ascii=False) + "\n"
        entry.proc.stdin.write(payload.encode("utf-8"))
        entry.proc.stdin.flush()
        entry.last_active = time.time()

        return self._read_until_result(entry, on_line)

    def _read_until_result(self, entry: ProcessEntry, on_line=None) -> Dict[str, Any]:
        """從 stdout 讀到 result 行為止。"""
        from app.core.stream_parsers import parse_stream_json_text, parse_stream_json_tokens

        result_text_parts = []
        token_info = {}

        while True:
            raw_line = entry.proc.stdout.readline()
            if not raw_line:
                # EOF — 進程退出了
                logger.warning(f"[ProcessPool] EOF for {entry.chat_key}")
                return {
                    "status": "error",
                    "output": "".join(result_text_parts) or "Process exited unexpectedly",
                    "token_info": token_info,
                }

            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("{"):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            # 逐行回呼（工具呼叫翻譯等）
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass

            # 收集 assistant 文字
            if msg_type == "assistant":
                text = parse_stream_json_text(line)
                if text:
                    result_text_parts.append(text)

            # result 行 = 這輪回應完成
            if msg_type == "result":
                token_info = parse_stream_json_tokens(line)
                entry.session_id = token_info.get("session_id") or entry.session_id
                entry.last_active = time.time()
                break

            # rate_limit / user 等其他行：跳過
            if msg_type in ("rate_limit_event", "user"):
                continue

        output = "".join(result_text_parts)
        return {
            "status": "success",
            "output": output,
            "token_info": token_info,
            "session_id": entry.session_id,
        }

    def _get_mcp_config(self, member_id: int) -> Optional[str]:
        """查找成員的 mcp.json 路徑。"""
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
        """安全 kill 進程。"""
        try:
            if entry.proc.poll() is None:
                entry.proc.stdin.close()
                entry.proc.kill()
                entry.proc.wait(timeout=5)
        except Exception:
            pass

    def _cleanup_loop(self):
        """背景清理過期進程。"""
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
                        reason = "TTL expired" if time.time() - entry.last_active > self._ttl else "process dead"
                        self._kill_entry(entry)
                        logger.info(f"[ProcessPool] Cleaned {key} ({reason})")
            except Exception as e:
                logger.warning(f"[ProcessPool] Cleanup error: {e}")


# 全域 singleton
process_pool = ProcessPool()

# 向後相容（worker.py 的 --resume 路徑仍用舊介面）
session_pool = process_pool  # type: ignore
