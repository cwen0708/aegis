"""
Talk WebSocket Endpoint — 即時語音對話（句子級 TTS streaming）

Protocol（client ↔ server）：
  Client → Server:
    JSON {"type": "audio_start"}                — 開始錄音
    binary bytes                                  — 音訊資料片段（audio_start 後）
      * Gemini 路徑：webm/opus 整段；audio_end 後一次性轉錄
      * ElevenLabs/Deepgram：PCM16 16kHz mono chunk（由前端 AudioWorklet 產生）
    JSON {"type": "audio_end"}                  — 結束錄音、觸發推論
    JSON {"type": "text_input", "text": "..."}  — 直接送文字（跳過 STT）

  Server → Client:
    JSON {"type": "state", "state": "idle" | "listening" | "thinking" | "speaking"}
    JSON {"type": "transcript_partial", "text": "...", "seq": N}  — 即時 STT（可被覆蓋）
    JSON {"type": "transcript", "text": "..."}  — STT 最終結果（final）
    JSON {"type": "llm_partial", "text": "..."} — AI 每句回覆（字幕即時累加）
    JSON {"type": "llm_response", "text": "..."} — AI 完整回覆文字（結尾一次）
    binary bytes                                  — TTS 音訊片段（MP3）
    JSON {"type": "audio_boundary"}             — 單句 TTS 結束（前端 flush 播放）
    JSON {"type": "audio_end"}                  — 全部 TTS 完成
    JSON {"type": "error", "error": "..."}      — 錯誤訊息

流程：
  - gemini：audio_end 整段 → _stt_gemini → LLM streaming → 切句 → TTS → WS
  - elevenlabs/deepgram：binary PCM chunk → streaming STT → partial/final
    → final 立即 kickoff LLM（不等 audio_end）→ 切句 → TTS → WS
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.core.stt_stream import StreamingSTT, get_streaming_stt
from app.core.tts import (
    ELEVENLABS_DEFAULT_VOICE_ID,
    _get_talk_tts_model,
    synthesize_elevenlabs_stream,
)
from app.database import engine
from app.models.core import Member, SystemSetting

router = APIRouter(tags=["talk"])
logger = logging.getLogger(__name__)


# 預設 STT provider（Card 1 seed 已設 elevenlabs）
_DEFAULT_STT_PROVIDER = "elevenlabs"


# ────────────────────────────────────────
# 設定讀取
# ────────────────────────────────────────

def _get_elevenlabs_api_key() -> Optional[str]:
    with Session(engine) as session:
        setting = session.get(SystemSetting, "elevenlabs_api_key")
        if setting and setting.value:
            return setting.value
    return None


def _get_gemini_api_key() -> Optional[str]:
    with Session(engine) as session:
        setting = session.get(SystemSetting, "gemini_api_key")
        if setting and setting.value:
            return setting.value
    return None


def _get_stt_provider() -> str:
    """讀 SystemSetting.stt_provider，預設 elevenlabs。"""
    with Session(engine) as session:
        setting = session.get(SystemSetting, "stt_provider")
        if setting and setting.value:
            return setting.value.strip().lower()
    return _DEFAULT_STT_PROVIDER


def _get_deepgram_api_key() -> Optional[str]:
    with Session(engine) as session:
        setting = session.get(SystemSetting, "deepgram_api_key")
        if setting and setting.value:
            return setting.value
    return None


def _extract_member_voice(member: Member) -> str:
    """從 member.extra_json 取 elevenlabs_voice_id，沒有則回預設值"""
    raw = getattr(member, "extra_json", None) or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    voice_id = data.get("elevenlabs_voice_id") or data.get("tts_voice_id")
    return voice_id or ELEVENLABS_DEFAULT_VOICE_ID


# ────────────────────────────────────────
# STT — Gemini multimodal（audio → text）
# ────────────────────────────────────────

async def _stt_gemini(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """用 Gemini multimodal 做語音轉文字。回空字串代表失敗。"""
    api_key = _get_gemini_api_key()
    if not api_key:
        logger.warning("[Talk] Gemini API key missing, cannot STT")
        return ""

    if not audio_bytes:
        return ""

    def _call() -> str:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            audio_part = types.Part.from_bytes(
                data=audio_bytes,
                mime_type=mime_type,
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    "請將這段音訊轉成繁體中文逐字稿，只輸出文字內容，不要加任何標點說明。",
                    audio_part,
                ],
            )
            text = (response.text or "").strip()
            return text
        except Exception as e:
            logger.warning(f"[Talk] Gemini STT failed: {e}")
            return ""

    return await asyncio.to_thread(_call)


# ────────────────────────────────────────
# 切句邏輯 — 中英標點 streaming 分句
# ────────────────────────────────────────

# 切句點：中文句號/問號/驚嘆號/分號、換行、英文句號（前後非數字）
SENTENCE_SPLIT_RE = re.compile(r"([。！？；!?\n]|(?<!\d)\.(?!\d))")

# 為避免 TTS 過度碎片化（例如每句 3~5 字），訂一個最短觸發長度
MIN_SENTENCE_LEN = 6


def split_sentences_streaming(buffer: str) -> tuple[list[str], str]:
    """從串流 buffer 切出完整句子。

    回傳: (完整句子列表, 剩餘未完成的尾端 buffer)
    """
    if not buffer:
        return [], ""

    parts = SENTENCE_SPLIT_RE.split(buffer)
    sentences: list[str] = []
    current = ""

    for p in parts:
        if p is None:
            continue
        if SENTENCE_SPLIT_RE.fullmatch(p):
            # 是標點
            current += p
            stripped = current.strip()
            if stripped and len(stripped) >= MIN_SENTENCE_LEN:
                sentences.append(stripped)
                current = ""
            # 太短就繼續累積到下一句
        else:
            current += p

    return sentences, current


# ────────────────────────────────────────
# LLM — 串流呼叫既有 member agent
# ────────────────────────────────────────

async def _stream_member_agent(
    member: Member,
    user_text: str,
    on_token: "asyncio.Queue[Optional[str]]",
) -> None:
    """串流呼叫 member agent，每收到一段 assistant 文字就 put 到 queue。

    底層 `process_pool.send_message` 提供 `on_line` callback，
    從 worker thread 抽取 assistant 片段並透過 run_coroutine_threadsafe 轉回 event loop。
    結束時 put None 作為哨兵。
    """
    from app.core.chat_workspace import ensure_chat_workspace
    from app.core.executor.context import resolve_member_for_chat
    from app.core.session_pool import process_pool
    from app.core.stream_parsers import parse_stream_json_text

    ctx = resolve_member_for_chat(member.id)
    if not ctx.has_member:
        await on_token.put(None)
        raise RuntimeError(f"成員 '{member.slug}' 無法載入")

    chat_key = f"talk_{member.slug}"
    ws_path = ensure_chat_workspace(
        member_slug=ctx.member_slug,
        chat_key=chat_key,
        bot_user_id=0,
        soul=ctx.soul,
    )

    prompt = (
        f"使用者透過語音對話向你說話：\n\n{user_text}\n\n"
        "請用口語化、簡短（1-3 句）的方式回應，因為會被轉成語音播放。"
        "不要用 markdown、表格、列表等格式。"
    )

    loop = asyncio.get_running_loop()

    def _on_line(line: str) -> None:
        text = parse_stream_json_text(line)
        if text:
            # 等 put 完成保證跨 thread 順序（無界 queue，成本極低）
            try:
                asyncio.run_coroutine_threadsafe(
                    on_token.put(text), loop
                ).result(timeout=5)
            except Exception as e:
                logger.debug(f"[Talk] on_line put failed: {e}")

    try:
        await asyncio.to_thread(
            process_pool.send_message,
            chat_key=chat_key,
            message=prompt,
            model=ctx.effective_model("chat"),
            member_id=ctx.member_id,
            auth_info=ctx.primary_auth,
            cwd=ws_path,
            on_line=_on_line,
        )
    finally:
        await on_token.put(None)


# ────────────────────────────────────────
# WebSocket endpoint
# ────────────────────────────────────────

async def _send_state(websocket: WebSocket, state: str) -> None:
    try:
        await websocket.send_json({"type": "state", "state": state})
    except Exception as e:
        logger.debug(f"[Talk] send_state failed: {e}")


async def _send_error(websocket: WebSocket, error: str) -> None:
    try:
        await websocket.send_json({"type": "error", "error": error})
    except Exception as e:
        logger.debug(f"[Talk] send_error failed: {e}")


async def _handle_turn(
    websocket: WebSocket,
    member: Member,
    user_text: str,
    voice_id: str,
    api_key: str,
) -> None:
    """處理單輪對話：LLM streaming → 切句 → TTS streaming → WS。

    Pipeline：
      producer: LLM 串流 → buffer → split_sentences_streaming → sentence_queue
      consumer: sentence_queue → synthesize_elevenlabs_stream → ws.send_bytes
                每句結束後送 `audio_boundary`，前端 flush 播放。
    """
    await _send_state(websocket, "thinking")

    token_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    full_response_parts: list[str] = []
    speaking_started = False
    # 每輪解析一次 TTS 模型（允許 admin 中途切換 A/B 模型）
    tts_model = _get_talk_tts_model()

    async def llm_producer() -> None:
        """從 LLM token stream 切句送入 sentence_queue。

        Claude CLI stream-json 的 assistant 行每次是**增量 delta**（參考
        runner.py 與 session_pool._read_until_result 的 result_text_parts.append
        用法），直接附加到 buffer 切句即可。
        """
        buffer = ""
        # 先啟動 LLM 串流任務（背景跑），這邊才消費 token_queue
        llm_task = asyncio.create_task(
            _stream_member_agent(member, user_text, token_queue)
        )
        try:
            while True:
                token = await token_queue.get()
                if token is None:
                    break
                buffer += token
                sentences, remaining = split_sentences_streaming(buffer)
                for s in sentences:
                    full_response_parts.append(s)
                    await sentence_queue.put(s)
                buffer = remaining

            # LLM 結束：殘留 buffer 也送出
            leftover = buffer.strip()
            if leftover:
                full_response_parts.append(leftover)
                await sentence_queue.put(leftover)

            # 確保底層任務完成（若已 put None 代表 _stream_member_agent 已退出）
            try:
                await llm_task
            except Exception as e:
                logger.warning(f"[Talk] LLM task failed: {e}")
        except Exception as e:
            logger.error(f"[Talk] LLM producer error: {e}")
            try:
                await _send_error(websocket, f"AI 回應失敗: {e}")
            except Exception:
                pass
        finally:
            await sentence_queue.put(None)

    async def tts_consumer() -> None:
        """從 sentence_queue 取句 → TTS stream → ws.send_bytes。"""
        nonlocal speaking_started
        try:
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    break
                if not sentence.strip():
                    continue

                if not speaking_started:
                    await _send_state(websocket, "speaking")
                    speaking_started = True

                # 字幕即時推送（選項 A：前端累加顯示）
                try:
                    await websocket.send_json(
                        {"type": "llm_partial", "text": sentence}
                    )
                except Exception:
                    pass

                # TTS 單句 streaming
                try:
                    async for chunk in synthesize_elevenlabs_stream(
                        sentence,
                        voice_id=voice_id,
                        api_key=api_key,
                        model=tts_model,
                    ):
                        await websocket.send_bytes(chunk)
                except Exception as e:
                    logger.warning(f"[Talk] TTS stream error for sentence: {e}")
                    continue

                # 單句結束 → 前端 flush 播放（句子邊界）
                try:
                    await websocket.send_json({"type": "audio_boundary"})
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[Talk] TTS consumer error: {e}")

    # 同時跑 producer 與 consumer
    await asyncio.gather(llm_producer(), tts_consumer(), return_exceptions=True)

    full_text = "".join(full_response_parts).strip()
    if not full_text:
        await _send_error(websocket, "AI 回應為空")
        await _send_state(websocket, "idle")
        return

    # 結尾送完整 llm_response 作為最終字幕（前端可覆蓋 partial）
    try:
        await websocket.send_json({"type": "llm_response", "text": full_text})
    except Exception:
        pass

    try:
        await websocket.send_json({"type": "audio_end"})
    except Exception:
        pass
    await _send_state(websocket, "idle")


async def _build_streaming_stt(provider: str) -> Optional[StreamingSTT]:
    """依 provider 建立 streaming STT；失敗回 None 讓 caller fallback。"""
    if provider == "gemini":
        return None
    try:
        keys = {
            "elevenlabs": _get_elevenlabs_api_key() or "",
            "deepgram": _get_deepgram_api_key() or "",
        }
        stt = get_streaming_stt(provider, api_keys=keys)
    except ValueError as e:
        logger.warning("[Talk] streaming STT disabled: %s", e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[Talk] streaming STT build failed: %s", e)
        return None

    if stt is None:
        return None

    try:
        await stt.start()
    except NotImplementedError as e:
        logger.warning("[Talk] provider %s not implemented: %s", provider, e)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[Talk] streaming STT start failed: %s", e)
        try:
            await stt.close()
        except Exception:  # noqa: BLE001
            pass
        return None

    return stt


@router.websocket("/ws/talk/{member_slug}")
async def talk_ws(websocket: WebSocket, member_slug: str) -> None:
    await websocket.accept()

    # 查成員
    with Session(engine) as session:
        member = session.exec(
            select(Member).where(Member.slug == member_slug)
        ).first()
        if not member:
            await _send_error(websocket, f"member {member_slug} not found")
            await websocket.close()
            return
        voice_id = _extract_member_voice(member)
        # detach：不繼續持 session 物件引用到 WS 迴圈中
        session.expunge(member)

    api_key = _get_elevenlabs_api_key()
    if not api_key:
        await _send_error(websocket, "ElevenLabs API key not configured")
        await websocket.close()
        return

    provider = _get_stt_provider()
    logger.info(
        f"[Talk] connected member={member_slug} voice_id={voice_id} stt={provider}"
    )
    await _send_state(websocket, "idle")

    # Streaming 狀態（每輪重建）
    audio_buffer = bytearray()  # gemini 路徑用
    stt: Optional[StreamingSTT] = None
    stt_provider: str = provider  # 本輪實際使用（可能因失敗降級為 gemini）
    final_text_holder: dict[str, str] = {"text": ""}
    llm_kickoff_task: Optional[asyncio.Task[None]] = None

    def _reset_turn_state() -> None:
        nonlocal audio_buffer, final_text_holder, llm_kickoff_task
        audio_buffer = bytearray()
        final_text_holder = {"text": ""}
        llm_kickoff_task = None

    async def _cleanup_stt() -> None:
        nonlocal stt
        if stt is not None:
            try:
                await stt.close()
            except Exception as e:  # noqa: BLE001
                logger.debug("[Talk] stt.close ignored: %s", e)
            stt = None

    async def _kickoff_llm_with_text(user_text: str) -> None:
        """STT final → 送 transcript + _handle_turn。"""
        try:
            await websocket.send_json({"type": "transcript", "text": user_text})
        except Exception as e:  # noqa: BLE001
            logger.debug("[Talk] send transcript failed: %s", e)
            return
        await _handle_turn(websocket, member, user_text, voice_id, api_key)

    def _make_partial_cb():
        async def _cb(text: str, seq: int) -> None:
            try:
                await websocket.send_json(
                    {"type": "transcript_partial", "text": text, "seq": seq}
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("[Talk] partial send failed: %s", e)
        return _cb

    def _make_final_cb():
        async def _cb(text: str) -> None:
            nonlocal llm_kickoff_task
            cleaned = (text or "").strip()
            if not cleaned:
                return
            final_text_holder["text"] = cleaned
            # 單輪 PTT 模式：LLM 只踢一次；後續 final 片段覆蓋文字不開新任務。
            # 免持（hands-free）模式：前端不送 audio_end，Eleven 自動 commit 多句。
            # 前一輪 task 已完成 → 允許踢下一輪，實現多輪對話。
            if llm_kickoff_task is None or llm_kickoff_task.done():
                # 清理已完成的上輪 final_text，避免 _wait_for_final 被舊文字卡住
                # （前端若切回 PTT 模式且送 audio_end 時才會用到 _wait_for_final）
                llm_kickoff_task = asyncio.create_task(
                    _kickoff_llm_with_text(cleaned),
                    name="talk-llm-kickoff",
                )
        return _cb

    def _make_error_cb():
        async def _cb(message: str) -> None:
            try:
                await websocket.send_json(
                    {"type": "error", "error": "stt_upstream_error"}
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("[Talk] error send failed: %s", e)
            logger.warning("[Talk] STT upstream error: %s", message)
        return _cb

    try:
        while True:
            msg = await websocket.receive()

            # 客戶端主動關閉
            if msg.get("type") == "websocket.disconnect":
                break

            # 二進位音訊片段
            if msg.get("bytes") is not None:
                chunk = msg["bytes"]
                if stt is not None:
                    try:
                        await stt.send_chunk(chunk)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[Talk] send_chunk failed: %s", e)
                else:
                    # gemini 整段路徑
                    audio_buffer.extend(chunk)
                continue

            text = msg.get("text")
            if text is None:
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                await _send_error(websocket, "無效的 JSON 訊息")
                continue

            event_type = data.get("type")

            if event_type == "audio_start":
                # 前一輪殘留清掉（保險）
                _reset_turn_state()
                await _cleanup_stt()

                # streaming provider：立刻建 session；失敗則降級 gemini
                if stt_provider in ("elevenlabs", "deepgram"):
                    stt = await _build_streaming_stt(stt_provider)
                    if stt is None:
                        logger.info(
                            "[Talk] fallback to gemini (streaming provider init failed)"
                        )
                        await _send_error(websocket, "stt_upstream_error")
                    else:
                        stt.on_partial = _make_partial_cb()
                        stt.on_final = _make_final_cb()
                        stt.on_error = _make_error_cb()

                await _send_state(websocket, "listening")
                continue

            if event_type == "audio_end":
                # Streaming 路徑：commit + close；LLM 可能已被 final 踢了
                if stt is not None:
                    try:
                        await stt.commit()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[Talk] stt.commit failed: %s", e)

                    # 等一個短窗口讓 final 回來（避免 audio_end 後立即關 ws）
                    try:
                        await asyncio.wait_for(
                            _wait_for_final(final_text_holder), timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        logger.info("[Talk] final transcript timeout after commit")

                    await _cleanup_stt()

                    # 沒踢過 LLM（例如 final 沒到）→ 顯式報錯
                    if llm_kickoff_task is None:
                        await _send_error(websocket, "STT 失敗或無語音內容")
                        await _send_state(websocket, "idle")
                    else:
                        # 等 LLM 任務跑完（若已在跑）
                        try:
                            await llm_kickoff_task
                        except Exception as e:  # noqa: BLE001
                            logger.debug("[Talk] llm task await: %s", e)
                    _reset_turn_state()
                    continue

                # Gemini 整段路徑（向後相容）
                raw_audio = bytes(audio_buffer)
                audio_buffer = bytearray()
                mime_type = data.get("mime_type") or "audio/webm"

                if not raw_audio:
                    await _send_error(websocket, "沒收到音訊")
                    await _send_state(websocket, "idle")
                    continue

                await _send_state(websocket, "thinking")
                user_text = await _stt_gemini(raw_audio, mime_type=mime_type)
                if not user_text:
                    await _send_error(websocket, "STT 失敗或無語音內容")
                    await _send_state(websocket, "idle")
                    continue

                await websocket.send_json(
                    {"type": "transcript", "text": user_text}
                )

                await _handle_turn(
                    websocket, member, user_text, voice_id, api_key
                )
                _reset_turn_state()
                continue

            if event_type == "text_input":
                user_text = (data.get("text") or "").strip()
                if not user_text:
                    await _send_error(websocket, "text_input 不能為空")
                    continue
                await _handle_turn(
                    websocket, member, user_text, voice_id, api_key
                )
                continue

            await _send_error(websocket, f"未知訊息類型: {event_type}")

    except WebSocketDisconnect:
        logger.info(f"[Talk] disconnected member={member_slug}")
    except Exception as e:
        logger.exception(f"[Talk] unexpected error: {e}")
        try:
            await _send_error(websocket, f"伺服器錯誤: {e}")
        except Exception:
            pass
    finally:
        await _cleanup_stt()
        try:
            await websocket.close()
        except Exception:
            pass


async def _wait_for_final(holder: dict[str, str]) -> None:
    """Poll helper — commit 後等 final 回來（跑滿 timeout 由 caller 控制）。"""
    while not holder.get("text"):
        await asyncio.sleep(0.05)
