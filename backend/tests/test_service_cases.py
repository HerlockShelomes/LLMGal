from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import requests

import Image
import Text
import Voice


def configure_tts(monkeypatch, tmp_path):
    monkeypatch.setattr(Voice, "VOICE_DIR", tmp_path / "voice")
    monkeypatch.setenv("LLMGAL_TTS_APP_ID", "test-app")
    monkeypatch.setenv("LLMGAL_TTS_TOKEN", "test-token")


def test_llm_01_role_prompt_includes_emotion_instruction(monkeypatch, tmp_path):
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "Wendy.txt").write_text("角色设定", encoding="utf-8")
    monkeypatch.setattr(Text, "ROLES_DIR", roles)
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="回复"))]
                )
            ]

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    monkeypatch.setattr(Text, "_create_client", lambda: client)
    result = Text.get_llm_response(
        "mock-model", "Wendy", {"role": "user", "content": "你好"}
    )
    system_prompt = captured["messages"][0]
    assert result == "回复"
    assert system_prompt["role"] == "assistant"
    assert system_prompt["content"].startswith("角色设定")
    for emotion in ("中性", "高兴", "悲伤", "害怕", "生气", "惊喜", "害羞"):
        assert emotion in system_prompt["content"]
    assert "不超过30字" in system_prompt["content"]
    assert "不得超过150字" in system_prompt["content"]


def test_tts_01_success_saves_decoded_audio_and_expected_payload(monkeypatch, tmp_path):
    configure_tts(monkeypatch, tmp_path)
    captured = {}
    audio = b"mock-mp3-bytes"

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": base64.b64encode(audio).decode("ascii")}

    def post(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(Voice.requests, "post", post)
    result = Voice.Voice_Generation_through_http(
        "Wendy", "voice-id", "happy", "测试文本", "3"
    )
    assert Path(result).read_bytes() == audio
    assert captured["timeout"] == 30
    assert captured["json"]["audio"]["voice_type"] == "voice-id"
    assert captured["json"]["request"]["text"] == "测试文本"


def test_tts_02_request_timeout_returns_empty_audio_result(monkeypatch, tmp_path):
    configure_tts(monkeypatch, tmp_path)

    def timeout(**_kwargs):
        raise requests.exceptions.Timeout("mock timeout")

    monkeypatch.setattr(Voice.requests, "post", timeout)
    result = Voice.Voice_Generation_through_http(
        "Wendy", "voice-id", "neutral", "测试", "3"
    )
    assert result == ""
    assert not (tmp_path / "voice").exists()


def test_tts_04_invalid_base64_does_not_create_audio_file(monkeypatch, tmp_path):
    configure_tts(monkeypatch, tmp_path)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": "%%%%"}

    monkeypatch.setattr(Voice.requests, "post", lambda **_kwargs: Response())
    result = Voice.Voice_Generation_through_http(
        "Wendy", "voice-id", "neutral", "测试", "3"
    )
    assert result == ""
    assert not (tmp_path / "voice" / "Wendy" / "Wendy_3_Stream.mp3").exists()


def test_tts_05_non_json_response_is_handled_without_uncaught_exception(monkeypatch, tmp_path):
    configure_tts(monkeypatch, tmp_path)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(Voice.requests, "post", lambda **_kwargs: Response())
    assert (
        Voice.Voice_Generation_through_http(
            "Wendy", "voice-id", "neutral", "测试", "3"
        )
        == ""
    )


def test_img_01_complete_static_image_set_skips_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(Image, "PICTURES_DIR", tmp_path)
    role_folder = tmp_path / "Wendy"
    role_folder.mkdir()
    for emotion, _description in Image.EMOTION_IMAGES:
        (role_folder / f"Wendy_{emotion}.jpg").write_bytes(b"image")

    def unexpected(*_args):
        raise AssertionError("complete static resources must not call image API")

    monkeypatch.setattr(Image, "original_image_generation", unexpected)
    monkeypatch.setattr(Image, "emotional_bro", unexpected)
    assert Image.static_images("Wendy", "mock-model") == ""


def test_img_02_missing_static_image_regenerates_seven_images(monkeypatch, tmp_path):
    monkeypatch.setattr(Image, "PICTURES_DIR", tmp_path)
    role_folder = tmp_path / "Wendy"
    role_folder.mkdir()
    for emotion, _description in Image.EMOTION_IMAGES[:-1]:
        (role_folder / f"Wendy_{emotion}.jpg").write_bytes(b"old")
    original_calls = []
    emotion_calls = []

    def original(role, description, index):
        original_calls.append((role, description, index))
        (role_folder / f"Wendy_{index}.jpg").write_bytes(b"new")
        return "initial-url"

    def emotional(url, role, emotion, index, model):
        emotion_calls.append((url, role, emotion, index, model))
        (role_folder / f"Wendy_{index}.jpg").write_bytes(b"new")
        return "generated-url"

    monkeypatch.setattr(Image, "original_image_generation", original)
    monkeypatch.setattr(Image, "emotional_bro", emotional)
    assert Image.static_images("Wendy", "mock-model") == "initial-url"
    assert len(original_calls) == 1
    assert len(emotion_calls) == 6
