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


def _get_tts_settings() -> tuple[bool, str]:
    """讀取 TTS 設定：(tts_enabled, tts_provider)
    tts_provider: 'web' | 'gemini' | 'ttsmaker'
    """
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            enabled = session.get(SystemSetting, "tts_enabled")
            provider = session.get(SystemSetting, "tts_provider")
            # 向後相容：舊的 tts_gemini=true → provider=gemini
            if not provider or not provider.value:
                gemini = session.get(SystemSetting, "tts_gemini")
                prov = "gemini" if (gemini and gemini.value == "true") else "web"
            else:
                prov = provider.value
            return (
                enabled and enabled.value == "true",
                prov,
            )
    except Exception:
        return False, "web"


def _get_ttsmaker_api_key() -> Optional[str]:
    """從 SystemSetting 讀取 TTSMaker API Key"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            setting = session.get(SystemSetting, "ttsmaker_api_key")
            if setting and setting.value:
                return setting.value
    except Exception:
        pass
    return None


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


async def synthesize_ttsmaker(text: str, voice_id: int = 1480, api_key: str = "") -> Optional[bytes]:
    """呼叫 TTSMaker API v2，回傳 MP3 bytes"""
    if not api_key:
        return None

    # 檢查快取
    cached = _cache_path(text, f"ttsmaker-{voice_id}")
    if cached.exists():
        return cached.read_bytes()

    def _call():
        import urllib.request
        import json as _json

        data = _json.dumps({
            "api_key": api_key,
            "text": text,
            "voice_id": voice_id,
            "audio_format": "mp3",
            "audio_speed": 1.0,
            "audio_volume": 1,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.ttsmaker.com/v2/create-tts-order",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = _json.loads(resp.read())

            if result.get("status") == "ok" and result.get("audio_file_url"):
                # 下載音檔
                audio_resp = urllib.request.urlopen(result["audio_file_url"], timeout=30)
                audio_data = audio_resp.read()

                # 寫入快取
                TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(audio_data)
                logger.info(f"[TTS] TTSMaker synthesized {len(text)} chars → {len(audio_data)} bytes")
                return audio_data

        except Exception as e:
            logger.warning(f"[TTS] TTSMaker synthesis failed: {e}")
        return None

    return await asyncio.to_thread(_call)


async def synthesize(text: str, voice: str = "Kore") -> Optional[bytes]:
    """TTS 入口：根據 tts_provider 設定選擇引擎"""
    tts_enabled, tts_provider = _get_tts_settings()

    if not tts_enabled:
        return None

    if tts_provider == "gemini":
        api_key = _get_gemini_api_key()
        if api_key:
            return await synthesize_gemini(text, voice=voice, api_key=api_key)

    elif tts_provider == "ttsmaker":
        api_key = _get_ttsmaker_api_key()
        if api_key:
            return await synthesize_ttsmaker(text, api_key=api_key)

    # web 或 fallback → 回 None，前端用 Web Speech
    return None
