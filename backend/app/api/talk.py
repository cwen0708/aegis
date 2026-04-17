"""
Talk WebSocket Endpoint — 即時語音對話（句子級 TTS streaming）

Protocol（client ↔ server）：
  Client → Server:
    JSON {"type": "audio_start"}                — 開始錄音
    binary bytes                                  — 音訊資料片段（audio_start 後）
    JSON {"type": "audio_end"}                  — 結束錄音、觸發推論
    JSON {"type": "text_input", "text": "..."}  — 直接送文字（跳過 STT）

  Server → Client:
    JSON {"type": "state", "state": "idle" | "listening" | "thinking" | "speaking"}
    JSON {"type": "transcript", "text": "..."}  — STT 結果
    JSON {"type": "llm_partial", "text": "..."} — AI 每句回覆（字幕即時累加）
    JSON {"type": "llm_response", "text": "..."} — AI 完整回覆文字（結尾一次）
    binary bytes                                  — TTS 音訊片段（MP3）
    JSON {"type": "audio_boundary"}             — 單句 TTS 結束（前端 flush 播放）
    JSON {"type": "audio_end"}                  — 全部 TTS 完成
    JSON {"type": "error", "error": "..."}      — 錯誤訊息

流程：audio_end / text_input → STT → LLM streaming → 切句 → ElevenLabs TTS → WS
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.core.tts import (
    ELEVENLABS_DEFAULT_MODEL,
    ELEVENLABS_DEFAULT_VOICE_ID,
    synthesize_elevenlabs_stream,
)
from app.database import engine
from app.models.core import Member, SystemSetting

router = APIRouter(tags=["talk"])
logger = logging.getLogger(__name__)


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
                        model=ELEVENLABS_DEFAULT_MODEL,
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

    logger.info(
        f"[Talk] connected member={member_slug} voice_id={voice_id}"
    )
    await _send_state(websocket, "idle")

    audio_buffer = bytearray()

    try:
        while True:
            msg = await websocket.receive()

            # 客戶端主動關閉
            if msg.get("type") == "websocket.disconnect":
                break

            # 二進位音訊片段
            if msg.get("bytes") is not None:
                audio_buffer.extend(msg["bytes"])
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
                audio_buffer = bytearray()
                await _send_state(websocket, "listening")
                continue

            if event_type == "audio_end":
                # 處理錄好的音訊
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
        try:
            await websocket.close()
        except Exception:
            pass
