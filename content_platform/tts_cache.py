"""Stable cache identity for synthesized speech."""

from __future__ import annotations

import hashlib
import json


def tts_fingerprint(*, display_text: str, tts_text: str, provider: str, model: str, voice: str, rate: str, pitch: str, pronunciation_dictionary_version: str, postprocess_profile: str) -> str:
    payload = {
        "display_text": display_text,
        "tts_text": tts_text,
        "provider": provider,
        "model": model,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
        "pronunciation_dictionary_version": pronunciation_dictionary_version,
        "postprocess_profile": postprocess_profile,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()
