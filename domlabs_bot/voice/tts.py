"""Text-to-speech for voice replies via Gemini.

Gated by ``config.VOICE_ENABLED``. When disabled or the optional ``google-genai``
package isn't installed, ``synthesize`` returns ``None`` silently so the caller
falls back to plain text.

Output is a single-channel 24 kHz WAV file written to a temp path. Telegram
accepts WAV under sendVoice (it'll re-encode to opus on its side).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import wave
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

DEFAULT_VOICE = "Charon"
MODEL = "gemini-2.5-flash-preview-tts"


def _write_wav(path: Path, pcm: bytes, sample_rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _synthesize_sync(text: str, voice: str, out: Path) -> bool:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.warning(
            "google-genai not installed; install with `pip install 'domlabs-bot[voice]'`"
        )
        return False
    if not config.GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set — cannot synthesize speech")
        return False
    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=MODEL,
            contents=text[:4000],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    )
                ),
            ),
        )
        audio = (
            resp.candidates[0]
            .content.parts[0]
            .inline_data.data
        )
        _write_wav(out, audio)
        return True
    except Exception:
        log.exception("gemini TTS failed")
        return False


async def synthesize(text: str, voice: str = DEFAULT_VOICE) -> Path | None:
    """Run Gemini TTS off the event loop. Returns path to a WAV file or None."""
    if not config.VOICE_ENABLED:
        return None
    if not text.strip():
        return None
    out = Path(tempfile.gettempdir()) / f"domlabs_tts_{os.getpid()}_{abs(hash(text))}.wav"
    ok = await asyncio.to_thread(_synthesize_sync, text, voice, out)
    if not ok:
        return None
    if not out.exists() or out.stat().st_size == 0:
        return None
    return out
