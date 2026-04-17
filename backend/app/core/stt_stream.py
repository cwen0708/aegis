"""
Streaming STT — 即時語音辨識抽象介面與 provider 實作

對應計畫 `~/.claude/plans/golden-jingling-galaxy.md` Step 2（Talk Phase 2）。

目前支援：
  - ElevenLabs Scribe v2 Realtime（WebSocket streaming，partial + committed）
  - Deepgram Nova-3（stub，Step 5 實作）
  - Gemini → 回 None，caller 走既有整段 buffer + multimodal 路徑（向後相容）

設計要點：
  - PCM 編碼由 **前端** AudioWorklet 完成（PCM16 16kHz mono），後端僅轉送
  - upstream 斷線採指數退避重連（500ms → 2s → 5s，最多 3 次）
  - partial transcript 附帶 `seq` 單調遞增序號，供前端去重
  - callback 執行在接收迴圈 task 中；caller 應確保 callback 不阻塞
"""
from __future__ import annotations

import abc
import asyncio
import base64
import json
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ────────────────────────────────────────
# 共用常數
# ────────────────────────────────────────

# ElevenLabs Scribe v2 Realtime 協議常數（驗證自官方 API 文件）
_ELEVENLABS_WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
_ELEVENLABS_CHUNK_MSG_TYPE = "input_audio_chunk"
_ELEVENLABS_DEFAULT_LANGUAGE = "zho"  # ISO 639-3（繁中/簡中共用底模）
_ELEVENLABS_DEFAULT_SAMPLE_RATE = 16000
_ELEVENLABS_PCM_FORMAT = "pcm_16000"

# 斷線重連退避（秒）
_RECONNECT_BACKOFFS = (0.5, 2.0, 5.0)


# ────────────────────────────────────────
# Callback 型別
# ────────────────────────────────────────

PartialCallback = Callable[[str, int], Optional[Awaitable[None]]]
FinalCallback = Callable[[str], Optional[Awaitable[None]]]
ErrorCallback = Callable[[str], Optional[Awaitable[None]]]


# ────────────────────────────────────────
# 抽象介面
# ────────────────────────────────────────

class StreamingSTT(abc.ABC):
    """即時串流 STT 抽象介面。

    生命週期：`start()` → 多次 `send_chunk()` → `commit()` → `close()`

    Callback 約定（caller 在 start 前設定）：
      - `on_partial(text, seq)`：收到 interim 結果，`seq` 為單調遞增序號
      - `on_final(text)`：收到 commit 後的最終片段
      - `on_error(message)`：upstream / protocol 錯誤（仍可由 caller 決定 fallback）
    """

    on_partial: Optional[PartialCallback] = None
    on_final: Optional[FinalCallback] = None
    on_error: Optional[ErrorCallback] = None

    @abc.abstractmethod
    async def start(self) -> None:
        """開啟 upstream 連線並送出 session 初始化設定。"""

    @abc.abstractmethod
    async def send_chunk(self, pcm_bytes: bytes) -> None:
        """送出一個 PCM16 @ 16kHz mono 音訊片段（由前端 AudioWorklet 產生）。"""

    @abc.abstractmethod
    async def commit(self) -> None:
        """告知語音結束，請求 upstream 輸出最終 transcript。"""

    @abc.abstractmethod
    async def close(self) -> None:
        """關閉連線並清理背景任務。"""


# ────────────────────────────────────────
# ElevenLabs Scribe v2 Realtime 實作
# ────────────────────────────────────────

class ElevenLabsStreamingSTT(StreamingSTT):
    """ElevenLabs Scribe v2 Realtime WebSocket streaming STT。

    官方端點：`wss://api.elevenlabs.io/v1/speech-to-text/realtime`
    Auth：HTTP header `xi-api-key`
    送訊息：`{"message_type":"input_audio_chunk","audio_base_64":"...","sample_rate":16000}`
    收訊息：`session_started` / `partial_transcript` / `committed_transcript`

    commit 策略：預設用 `vad`（讓 provider 自己判斷斷句），
    caller 呼叫 `commit()` 時額外送一個 `commit=true` 的空 chunk 強制刷新。
    """

    def __init__(
        self,
        api_key: str,
        language_code: str = _ELEVENLABS_DEFAULT_LANGUAGE,
        sample_rate: int = _ELEVENLABS_DEFAULT_SAMPLE_RATE,
        commit_strategy: str = "vad",
    ) -> None:
        if not api_key:
            raise ValueError("ElevenLabs API key required")
        self._api_key = api_key
        self._language_code = language_code
        self._sample_rate = sample_rate
        self._commit_strategy = commit_strategy

        self._ws = None  # type: ignore[assignment]
        self._recv_task: Optional[asyncio.Task[None]] = None
        self._partial_seq: int = 0
        self._closed: bool = False
        self._reconnect_attempts: int = 0

    # ── 連線管理 ──────────────────────────────

    async def start(self) -> None:
        """建立 WS 連線並送 session 初始化設定。"""
        await self._open_ws()

    async def _open_ws(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "websockets package required for ElevenLabsStreamingSTT"
            ) from e

        headers = [("xi-api-key", self._api_key)]
        try:
            self._ws = await connect(
                _ELEVENLABS_WS_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                max_size=None,  # transcript 可能較大
            )
        except Exception as e:
            logger.warning("[STT] ElevenLabs connect failed: %s", e)
            raise

        # Session 初始化（audio_format / language / commit strategy）
        init_msg = {
            "message_type": "session_config",
            "audio_format": _ELEVENLABS_PCM_FORMAT,
            "language_code": self._language_code,
            "commit_strategy": self._commit_strategy,
        }
        try:
            await self._ws.send(json.dumps(init_msg))
        except Exception as e:
            logger.warning("[STT] ElevenLabs init send failed: %s", e)
            raise

        # 啟動接收迴圈
        self._recv_task = asyncio.create_task(
            self._recv_loop(), name="elevenlabs-stt-recv"
        )
        logger.info(
            "[STT] ElevenLabs session started (lang=%s, commit=%s)",
            self._language_code,
            self._commit_strategy,
        )

    # ── 傳送音訊 ──────────────────────────────

    async def send_chunk(self, pcm_bytes: bytes) -> None:
        if self._closed or not pcm_bytes:
            return
        if self._ws is None:
            await self._ensure_reconnect()
            if self._ws is None:
                return

        payload = {
            "message_type": _ELEVENLABS_CHUNK_MSG_TYPE,
            "audio_base_64": base64.b64encode(pcm_bytes).decode("ascii"),
            "sample_rate": self._sample_rate,
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.warning("[STT] ElevenLabs send_chunk failed: %s", e)
            await self._ensure_reconnect()

    async def commit(self) -> None:
        """顯式 commit：送一個標記 commit=true 的空 chunk 強制 provider 刷新 final。"""
        if self._closed or self._ws is None:
            return
        payload = {
            "message_type": _ELEVENLABS_CHUNK_MSG_TYPE,
            "audio_base_64": "",
            "sample_rate": self._sample_rate,
            "commit": True,
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.warning("[STT] ElevenLabs commit failed: %s", e)

    # ── 接收迴圈 ──────────────────────────────

    async def _recv_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    # 協議文件未定義 binary 回傳，忽略
                    continue
                await self._handle_server_message(raw)
        except Exception as e:
            # 連線斷開 / 讀取失敗
            logger.info("[STT] ElevenLabs recv loop ended: %s", e)
            if not self._closed:
                await self._fire_error(f"stt_upstream_error: {e}")

    async def _handle_server_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("[STT] ElevenLabs non-JSON message: %s", raw[:120])
            return

        mtype = msg.get("message_type") or msg.get("type") or ""

        # 正常事件
        if mtype in ("session_started",):
            return

        if mtype == "partial_transcript":
            text = _extract_transcript_text(msg)
            if text:
                self._partial_seq += 1
                await self._fire_partial(text, self._partial_seq)
            return

        if mtype in ("committed_transcript", "committed_transcript_with_timestamps"):
            text = _extract_transcript_text(msg)
            if text:
                await self._fire_final(text)
            return

        # 錯誤類事件
        if mtype in (
            "error",
            "auth_error",
            "quota_exceeded",
            "rate_limited",
            "queue_overflow",
            "resource_exhausted",
            "session_time_limit_exceeded",
            "input_error",
            "chunk_size_exceeded",
            "transcriber_error",
            "commit_throttled",
        ):
            err = msg.get("error") or msg.get("message") or mtype
            logger.warning("[STT] ElevenLabs error event: %s", err)
            await self._fire_error(str(err))
            return

        if mtype == "insufficient_audio_activity":
            # 資訊性訊息，不視為錯誤
            logger.debug("[STT] ElevenLabs insufficient_audio_activity")
            return

        logger.debug("[STT] ElevenLabs unknown message: %s", mtype)

    # ── 重連 ─────────────────────────────────

    async def _ensure_reconnect(self) -> None:
        if self._closed:
            return
        if self._reconnect_attempts >= len(_RECONNECT_BACKOFFS):
            logger.error("[STT] ElevenLabs reconnect exhausted")
            await self._fire_error("stt_upstream_reconnect_exhausted")
            return

        backoff = _RECONNECT_BACKOFFS[self._reconnect_attempts]
        self._reconnect_attempts += 1
        logger.info(
            "[STT] ElevenLabs reconnect attempt %d after %.1fs",
            self._reconnect_attempts,
            backoff,
        )
        await asyncio.sleep(backoff)
        await self._close_ws_silently()
        try:
            await self._open_ws()
        except Exception as e:
            logger.warning("[STT] ElevenLabs reconnect failed: %s", e)
            await self._fire_error(f"stt_upstream_reconnect_failed: {e}")

    # ── 關閉 ─────────────────────────────────

    async def close(self) -> None:
        self._closed = True
        await self._close_ws_silently()
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._recv_task = None
        logger.info("[STT] ElevenLabs session closed")

    async def _close_ws_silently(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("[STT] ElevenLabs ws close ignored: %s", e)

    # ── Callback dispatch ────────────────────

    async def _fire_partial(self, text: str, seq: int) -> None:
        cb = self.on_partial
        if cb is None:
            return
        try:
            result = cb(text, seq)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            logger.warning("[STT] on_partial callback error: %s", e)

    async def _fire_final(self, text: str) -> None:
        cb = self.on_final
        if cb is None:
            return
        try:
            result = cb(text)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            logger.warning("[STT] on_final callback error: %s", e)

    async def _fire_error(self, message: str) -> None:
        cb = self.on_error
        if cb is None:
            return
        try:
            result = cb(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            logger.warning("[STT] on_error callback error: %s", e)


def _extract_transcript_text(msg: dict) -> str:
    """從 partial_transcript / committed_transcript payload 抽出純文字。

    官方 payload 可能使用 `text`、`transcript` 或嵌套 `data.text`，保守全部嘗試。
    """
    for key in ("text", "transcript"):
        val = msg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    data = msg.get("data")
    if isinstance(data, dict):
        for key in ("text", "transcript"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    # words[] timestamp payload fallback
    words = msg.get("words")
    if isinstance(words, list):
        parts = [w.get("text", "") for w in words if isinstance(w, dict)]
        joined = "".join(parts).strip()
        if joined:
            return joined
    return ""


# ────────────────────────────────────────
# Deepgram Nova-3 stub（Step 5 實作）
# ────────────────────────────────────────

class DeepgramStreamingSTT(StreamingSTT):
    """Deepgram Nova-3 streaming STT — 預留 stub，Step 5 實作。

    計畫 endpoint：
      wss://api.deepgram.com/v1/listen?model=nova-3&language=zh-TW
      &interim_results=true&endpointing=300&encoding=linear16&sample_rate=16000
    """

    def __init__(self, api_key: str, language_code: str = "zh-TW") -> None:
        self._api_key = api_key
        self._language_code = language_code

    async def start(self) -> None:
        raise NotImplementedError(
            "DeepgramStreamingSTT not yet implemented (planned for Step 5)"
        )

    async def send_chunk(self, pcm_bytes: bytes) -> None:
        raise NotImplementedError

    async def commit(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        # 允許 close 是 no-op，方便 caller 無條件清理
        return None


# ────────────────────────────────────────
# Factory
# ────────────────────────────────────────

def get_streaming_stt(
    provider: str,
    api_keys: Optional[dict] = None,
) -> Optional[StreamingSTT]:
    """依 provider 名稱建立對應的 StreamingSTT。

    Parameters
    ----------
    provider : {"gemini","elevenlabs","deepgram"}
        設定來源為 SystemSetting.stt_provider。
    api_keys : dict
        {"elevenlabs": "...", "deepgram": "..."}；缺 key 會 raise。

    Returns
    -------
    StreamingSTT | None
        - `gemini` 回 None（caller 走整段 buffer + multimodal 路徑）
        - `elevenlabs` 回 ElevenLabsStreamingSTT
        - `deepgram` 回 DeepgramStreamingSTT（目前 stub）
    """
    keys = api_keys or {}
    name = (provider or "").strip().lower()

    if name in ("gemini", ""):
        return None

    if name == "elevenlabs":
        key = (keys.get("elevenlabs") or "").strip()
        if not key:
            raise ValueError("elevenlabs_api_key missing for streaming STT")
        return ElevenLabsStreamingSTT(api_key=key)

    if name == "deepgram":
        key = (keys.get("deepgram") or "").strip()
        if not key:
            raise ValueError("deepgram_api_key missing for streaming STT")
        return DeepgramStreamingSTT(api_key=key)

    raise ValueError(f"unknown stt_provider: {provider!r}")
