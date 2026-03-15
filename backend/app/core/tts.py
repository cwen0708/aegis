"""
TTS 語音合成 — Gemini TTS + Web Speech API 降級

用於 AVG 角色對話的語音播放。
Gemini TTS 回傳 PCM 24kHz mono → 轉 WAV → 回傳給前端播放。
"""
import asyncio
import hashlib
import io
import logging
import struct
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 快取目錄
TTS_CACHE_DIR = Path("/tmp/aegis-tts")


def _get_gemini_api_key() -> Optional[str]:
    """從 SystemSetting 讀取 Gemini API Key"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            setting = session.get(SystemSetting, "gemini_api_key")
            if setting and setting.value:
                return setting.value
    except Exception:
        pass
    return None


def _get_tts_settings() -> tuple[bool, bool]:
    """讀取 TTS 設定：(tts_enabled, tts_gemini)"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            enabled = session.get(SystemSetting, "tts_enabled")
            gemini = session.get(SystemSetting, "tts_gemini")
            return (
                enabled and enabled.value == "true",
                gemini and gemini.value == "true",
            )
    except Exception:
        return False, False


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """將 PCM raw bytes 轉成 WAV 格式"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _cache_path(text: str, voice: str) -> Path:
    """產生快取檔案路徑"""
    key = hashlib.md5(f"{text}:{voice}".encode()).hexdigest()
    return TTS_CACHE_DIR / f"{key}.wav"


async def synthesize_gemini(text: str, voice: str = "Kore", api_key: str = "") -> Optional[bytes]:
    """呼叫 Gemini TTS API，回傳 WAV bytes"""
    if not api_key:
        return None

    # 檢查快取
    cached = _cache_path(text, voice)
    if cached.exists():
        return cached.read_bytes()

    def _call():
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice
                            )
                        )
                    ),
                ),
            )

            # 取得 PCM audio data
            part = response.candidates[0].content.parts[0]
            if part.inline_data and part.inline_data.data:
                pcm_data = part.inline_data.data
                # 如果是 bytes string（base64），解碼
                if isinstance(pcm_data, str):
                    import base64
                    pcm_data = base64.b64decode(pcm_data)
                wav_data = _pcm_to_wav(pcm_data)

                # 寫入快取
                TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(wav_data)
                logger.info(f"[TTS] Gemini synthesized {len(text)} chars → {len(wav_data)} bytes WAV")
                return wav_data

        except Exception as e:
            logger.warning(f"[TTS] Gemini synthesis failed: {e}")
        return None

    return await asyncio.to_thread(_call)


async def synthesize(text: str, voice: str = "Kore") -> Optional[bytes]:
    """TTS 入口：有 Gemini key 且啟用就用 Gemini，否則回 None（前端降級到 Web Speech）"""
    tts_enabled, tts_gemini = _get_tts_settings()

    if not tts_enabled:
        return None

    if tts_gemini:
        api_key = _get_gemini_api_key()
        if api_key:
            return await synthesize_gemini(text, voice=voice, api_key=api_key)

    # 沒有 Gemini → 回 None，前端用 Web Speech
    return None
