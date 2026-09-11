"""HTTP text-to-speech adapter and local audio persistence."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from pathlib import Path

import requests


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VOICE_DIR = REPOSITORY_ROOT / "frontend" / "src" / "assets" / "voice"
TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"


def save_audio_from_base64(audio: str, role: str, index: str) -> str:
    """Decode non-empty, strictly valid Base64 data into one MP3 file."""

    try:
        audio_data = base64.b64decode(audio, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return ""
    if not audio_data:
        return ""

    save_path = Path(VOICE_DIR) / role / f"{role}_{index}_Stream.mp3"
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(audio_data)
    except OSError:
        return ""
    return str(save_path)


def _tts_configuration() -> tuple[str, str, str] | None:
    app_id = os.getenv("LLMGAL_TTS_APP_ID", "")
    token = os.getenv("LLMGAL_TTS_TOKEN", "")
    cluster = os.getenv("LLMGAL_TTS_CLUSTER", "volcano_tts")
    if not app_id or not token:
        return None
    return app_id, token, cluster


def Voice_Generation_through_http(
    role: str,
    voice_type: str,
    emotion: str,
    text: str,
    index: str,
) -> str:
    """Synthesize speech; return an empty path for controlled service failures."""

    configuration = _tts_configuration()
    if configuration is None:
        return ""
    app_id, token, cluster = configuration
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer; {token}",
    }
    payload = {
        "app": {"appid": app_id, "token": token, "cluster": cluster},
        "user": {"uid": "llmgal-module1"},
        "audio": {
            "voice_type": voice_type,
            "enable_emotion": True,
            "emotion": emotion,
            "emotion_scale": 5,
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "explicit_language": "zh",
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
            "disable_markdown_filter": True,
        },
        "extra_param": json.dumps(
            {"cache_config": {"text_type": 1, "use_cache": True}}
        ),
    }

    try:
        response = requests.post(
            url=TTS_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        response_data = response.json()
        encoded_audio = response_data["data"]
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        return ""
    return save_audio_from_base64(encoded_audio, role, index)
