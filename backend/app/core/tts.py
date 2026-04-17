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


def _get_elevenlabs_api_key() -> Optional[str]:
    """從 SystemSetting 讀取 ElevenLabs API Key"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import SystemSetting
        with Session(engine) as session:
            setting = session.get(SystemSetting, "elevenlabs_api_key")
            if setting and setting.value:
                return setting.value
    except Exception:
        pass
    return None


def _get_tts_settings() -> tuple[bool, str]:
    """讀取 TTS 設定：(tts_enabled, tts_provider)
    tts_provider: 'web' | 'gemini' | 'ttsmaker' | 'elevenlabs'
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


ELEVENLABS_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (公開示範 voice)
ELEVENLABS_DEFAULT_MODEL = "eleven_multilingual_v2"


async def synthesize_elevenlabs(
    text: str,
    voice_id: str = ELEVENLABS_DEFAULT_VOICE_ID,
    api_key: str = "",
    model: str = ELEVENLABS_DEFAULT_MODEL,
) -> Optional[bytes]:
    """呼叫 ElevenLabs TTS API（非 streaming），回傳 MP3 bytes"""
    if not api_key:
        return None

    cached = _cache_path(text, f"elevenlabs-{voice_id}-{model}")
    if cached.exists():
        return cached.read_bytes()

    def _call() -> Optional[bytes]:
        try:
            import requests
        except ImportError:
            logger.warning("[TTS] requests module not available for ElevenLabs")
            return None

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=60)
        except Exception as e:
            logger.warning(f"[TTS] ElevenLabs request failed: {e}")
            return None

        if resp.status_code != 200:
            logger.error(
                f"[TTS] ElevenLabs failed {resp.status_code}: {resp.text[:200]}"
            )
            return None

        audio_data = resp.content
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(audio_data)
        logger.info(
            f"[TTS] ElevenLabs synthesized {len(text)} chars → {len(audio_data)} bytes"
        )
        return audio_data

    return await asyncio.to_thread(_call)


async def synthesize_elevenlabs_stream(
    text: str,
    voice_id: str = ELEVENLABS_DEFAULT_VOICE_ID,
    api_key: str = "",
    model: str = ELEVENLABS_DEFAULT_MODEL,
    chunk_size: int = 4096,
):
    """ElevenLabs TTS streaming，非同步 yield MP3 chunks。

    使用 `asyncio.to_thread` 包住 blocking `requests.iter_content`，
    每個 chunk 透過 `asyncio.Queue` 橋接到 async generator。
    """
    if not api_key:
        return

    import queue as _queue
    import threading

    try:
        import requests
    except ImportError:
        logger.warning("[TTS] requests module not available for ElevenLabs stream")
        return

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    _SENTINEL: object = object()

    def _producer() -> None:
        try:
            resp = requests.post(
                url, headers=headers, json=body, stream=True, timeout=60
            )
            if resp.status_code != 200:
                logger.error(
                    f"[TTS] ElevenLabs stream failed {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                return
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    asyncio.run_coroutine_threadsafe(q.put(chunk), loop).result()
        except Exception as e:
            logger.warning(f"[TTS] ElevenLabs streaming error: {e}")
        finally:
            asyncio.run_coroutine_threadsafe(q.put(_SENTINEL), loop).result()

    thread = threading.Thread(target=_producer, daemon=True)
    thread.start()

    while True:
        item = await q.get()
        if item is _SENTINEL:
            break
        yield item


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

    elif tts_provider == "elevenlabs":
        api_key = _get_elevenlabs_api_key()
        if api_key:
            # voice 參數在此 provider 當作 voice_id 使用（若非預設 "Kore"）
            voice_id = voice if voice and voice != "Kore" else ELEVENLABS_DEFAULT_VOICE_ID
            return await synthesize_elevenlabs(text, voice_id=voice_id, api_key=api_key)

    # web 或 fallback → 回 None，前端用 Web Speech
    return None
