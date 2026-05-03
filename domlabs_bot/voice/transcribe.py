"""Transcribe voice notes via Gemini audio understanding.

Gated by ``config.VOICE_ENABLED``. If voice is disabled or the Gemini key
is missing, returns ``None`` silently so callers can degrade to text-only.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from .. import config

log = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


async def transcribe_audio(path: Path, mime: str = "audio/ogg") -> str | None:
    """Return a plain-text transcript of the audio file, or None on failure."""
    if not config.VOICE_ENABLED:
        return None
    if not config.GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set — cannot transcribe")
        return None
    data_b64 = base64.b64encode(path.read_bytes()).decode()
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Transcribe this audio verbatim. Output only the "
                            "transcription — no preamble, no commentary."
                        )
                    },
                    {"inline_data": {"mime_type": mime, "data": data_b64}},
                ]
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                URL, params={"key": config.GEMINI_API_KEY}, json=payload
            )
        if resp.status_code != 200:
            log.warning(
                "gemini transcribe failed: %s %s", resp.status_code, resp.text[:300]
            )
            return None
        body = resp.json()
        parts = (
            body.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception:
        log.exception("transcribe crashed")
        return None
