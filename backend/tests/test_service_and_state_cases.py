from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
import requests

import Image
import Integration
import Text
import Voice


FIXED_REPLY = "(高兴)(收到邀请很开心)你好呀"


def make_workspace(monkeypatch, tmp_path: Path, *, role="Wendy", index="3"):
    backend_dir = tmp_path / "backend"
    assets = tmp_path / "frontend" / "src" / "assets"
    backend_dir.mkdir(exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    records = assets / "Records.txt"
    records.write_text(
        f"{role}:\nRecent_Url:old-url\nindex:{index}\n", encoding="utf-8"
    )
    monkeypatch.chdir(backend_dir)
    return assets, records


def prepare_collection(monkeypatch, tmp_path, *, answer=FIXED_REPLY, index="3"):
    _assets, records = make_workspace(monkeypatch, tmp_path, index=index)
    voice_calls = []
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: answer)
    monkeypatch.setattr(
        Integration,
        "Voice_Generation_through_http",
        lambda *args: voice_calls.append(args) or "fixed-audio.mp3",
    )
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "")
    return records, voice_calls


def call_collection(*, realtime=False, image_model="mock-image"):
    return Integration.Response_Collection(
        "mock-model",
        image_model,
        "Wendy",
        "ElderSister",
        realtime,
        {"role": "user", "content": "你好"},
    )


def test_tc_cfg_04_supported_voice_categories_map_correctly():
    """TC-CFG-04：四类有效音色映射正确。"""
    expected = {
        "GirlFriend": "zh_female_tianxinxiaomei_emo_v2_mars_bigtts",
        "BoyFriend": "zh_male_yourougongzi_emo_v2_mars_bigtts",
        "ElderSister": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
        "LiteratureGuy": "zh_male_ruyayichen_emo_v2_mars_bigtts",
    }
    actual = {
        category: Integration.request_confirmation(category, "中性")[0]
        for category in expected
    }
    assert actual == expected


def test_tc_cfg_05_unknown_voice_uses_default():
    """TC-CFG-05：未知音色回退为默认女声。"""
    expected = Integration.request_confirmation("GirlFriend", "中性")[0]
    assert Integration.request_confirmation("UnknownVoice", "中性")[0] == expected


def test_tc_llm_01_role_prompt_appends_emotion_constraints(monkeypatch, tmp_path):
    """TC-LLM-01：角色 Prompt 读取并追加完整情绪输出约束。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    roles = assets / "roles"
    roles.mkdir()
    (roles / "Wendy.txt").write_text("固定角色描述", encoding="utf-8")
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="固定回复"))
                    ]
                )
            ]

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(Text, "OpenAI", lambda **_kwargs: client)
    assert Text.get_llm_response(
        "mock-model", "Wendy", {"role": "user", "content": "你好"}
    ) == "固定回复"
    system_prompt = captured["messages"][0]
    assert system_prompt["role"] == "assistant"
    assert system_prompt["content"].startswith("固定角色描述")
    for emotion in ("中性", "高兴", "悲伤", "害怕", "生气", "惊喜", "害羞"):
        assert emotion in system_prompt["content"]
    assert "不超过30字" in system_prompt["content"]
    assert "不得超过150字" in system_prompt["content"]


def test_tc_llm_03_no_parentheses_defaults_to_neutral(monkeypatch, tmp_path):
    """TC-LLM-03：无括号时使用中性情绪。"""
    _records, voice_calls = prepare_collection(
        monkeypatch, tmp_path, answer="普通回复"
    )
    result = call_collection()
    assert result[0] == "普通回复"
    assert result[2] == "neutral"
    assert voice_calls[0][2] == "neutral"


def test_tc_llm_04_one_parenthesis_uses_empty_reason(monkeypatch, tmp_path):
    """TC-LLM-04：一个括号时原因使用空串。"""
    prepare_collection(monkeypatch, tmp_path, answer="(悲伤)回复正文")
    image_calls = []
    monkeypatch.setattr(
        Integration,
        "emotional_bro",
        lambda *args: image_calls.append(args) or "fixed-url",
    )
    result = call_collection(realtime=True)
    assert result[2] == "sad"
    assert image_calls[0][2] == ["悲伤", ""]


def test_tc_llm_05_extra_parentheses_are_ignored(monkeypatch, tmp_path):
    """TC-LLM-05：两个以上括号时忽略第三项以后内容。"""
    prepare_collection(
        monkeypatch, tmp_path, answer="(惊喜)(因为收到礼物)(额外描述)正文"
    )
    image_calls = []
    monkeypatch.setattr(
        Integration,
        "emotional_bro",
        lambda *args: image_calls.append(args) or "fixed-url",
    )
    result = call_collection(realtime=True)
    assert result[2] == "surprised"
    assert image_calls[0][2] == ["惊喜", "因为收到礼物"]


def test_tc_tts_01_valid_base64_is_saved_with_expected_payload(monkeypatch, tmp_path):
    """TC-TTS-01：合法 Base64 音频保存且请求参数正确。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    captured = {}
    audio = b"fixed-mp3-bytes"

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
        "Wendy", "fixed-voice", "happy", "固定文本", "3"
    )
    assert Path(result).read_bytes() == audio
    assert (assets / "voice" / "Wendy" / "Wendy_3_Stream.mp3").read_bytes() == audio
    assert captured["timeout"] == 30
    assert captured["json"]["audio"]["voice_type"] == "fixed-voice"
    assert captured["json"]["audio"]["emotion"] == "happy"
    assert captured["json"]["request"]["text"] == "固定文本"


def test_tc_tts_02_timeout_returns_empty_and_flow_continues(monkeypatch, tmp_path):
    """TC-TTS-02：TTS 超时返回空串，图片与 Records 流程继续。"""
    _assets, records = make_workspace(monkeypatch, tmp_path)

    def timeout(**_kwargs):
        raise requests.exceptions.Timeout("fixed timeout")

    monkeypatch.setattr(Voice.requests, "post", timeout)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: FIXED_REPLY)
    monkeypatch.setattr(
        Integration, "Voice_Generation_through_http", Voice.Voice_Generation_through_http
    )
    image_calls = []
    monkeypatch.setattr(
        Integration,
        "static_images",
        lambda *args: image_calls.append(args) or "",
    )
    result = call_collection()
    assert result[0] == FIXED_REPLY
    assert image_calls == [("Wendy", "mock-image")]
    assert "index:4" in records.read_text(encoding="utf-8")


@pytest.mark.xfail(strict=True, reason="TC-TTS-04：当前实现会写入零字节音频")
def test_tc_tts_04_invalid_base64_must_not_create_audio(monkeypatch, tmp_path):
    """TC-TTS-04：非法 Base64 应返回空串且不创建有效 mp3。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    result = Voice.save_audio_from_base64("%%%%", "Wendy", "3")
    assert result == ""
    assert not (assets / "voice" / "Wendy" / "Wendy_3_Stream.mp3").exists()


def test_tc_tts_05_non_json_response_propagates_error(monkeypatch, tmp_path):
    """TC-TTS-05：非 JSON 响应异常向上触发处理错误路径。"""
    make_workspace(monkeypatch, tmp_path)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("fixed non-json response")

    monkeypatch.setattr(Voice.requests, "post", lambda **_kwargs: Response())
    with pytest.raises(ValueError, match="non-json"):
        Voice.Voice_Generation_through_http(
            "Wendy", "fixed-voice", "neutral", "固定文本", "3"
        )


def test_tc_img_01_seven_static_images_skip_generation(monkeypatch, tmp_path):
    """TC-IMG-01：恰好七张静态情绪图时跳过生成。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    role_dir = assets / "pictures" / "Wendy"
    role_dir.mkdir(parents=True)
    for emotion, _description in Image.emo_image:
        (role_dir / f"Wendy_{emotion}.jpg").write_bytes(b"fixed")

    def unexpected(*_args):
        raise AssertionError("完整静态资源不应调用图片生成服务")

    monkeypatch.setattr(Image, "original_image_generation", unexpected)
    monkeypatch.setattr(Image, "emotional_bro", unexpected)
    assert Image.static_images("Wendy", "mock-image") == ""


def test_tc_img_02_six_static_images_trigger_regeneration(monkeypatch, tmp_path):
    """TC-IMG-02：缺一张静态图时生成 neutral 和其余六种情绪。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    role_dir = assets / "pictures" / "Wendy"
    role_dir.mkdir(parents=True)
    for emotion, _description in Image.emo_image[:-1]:
        (role_dir / f"Wendy_{emotion}.jpg").write_bytes(b"fixed")
    original_calls = []
    emotional_calls = []
    monkeypatch.setattr(
        Image,
        "original_image_generation",
        lambda *args: original_calls.append(args) or "initial-url",
    )
    monkeypatch.setattr(
        Image,
        "emotional_bro",
        lambda *args: emotional_calls.append(args) or "generated-url",
    )
    assert Image.static_images("Wendy", "mock-image") == "initial-url"
    assert len(original_calls) == 1
    assert len(emotional_calls) == 6


def test_tc_img_03_realtime_generation_uses_recent_url(monkeypatch, tmp_path):
    """TC-IMG-03：实时图生图使用 Records URL、写图片并更新记录。"""
    assets, records = make_workspace(monkeypatch, tmp_path)
    prepare_collection(monkeypatch, tmp_path)
    captured = {}

    class VisualService:
        def set_ak(self, value):
            captured["ak_set"] = bool(value)

        def set_sk(self, value):
            captured["sk_set"] = bool(value)

        def cv_process(self, form):
            captured["form"] = form
            return {"data": {"image_urls": ["new-image-url"]}}

    def fixed_download(_url, save_path):
        path = (Path.cwd() / save_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixed-image")
        return True

    monkeypatch.setattr(Image, "VisualService", VisualService)
    monkeypatch.setattr(Image, "save_image_from_url", fixed_download)
    monkeypatch.setattr(Integration, "emotional_bro", Image.emotional_bro)
    result = call_collection(realtime=True, image_model="high_aes_ip_v20")
    assert captured["form"]["req_key"] == "high_aes_ip_v20"
    assert captured["form"]["image_urls"] == ["old-url"]
    assert result[3] == "new-image-url"
    assert (assets / "pictures" / "Wendy" / "Wendy_3.jpg").read_bytes() == b"fixed-image"
    assert "Recent_Url:new-image-url\nindex:4" in records.read_text(encoding="utf-8")


def test_tc_img_04_realtime_failure_falls_back_to_original(monkeypatch, tmp_path):
    """TC-IMG-04：实时图失败后回退文生图并更新 Records。"""
    records, _voice_calls = prepare_collection(monkeypatch, tmp_path)
    fallback_calls = []

    def fail(*_args):
        raise RuntimeError("fixed expired URL")

    monkeypatch.setattr(Integration, "emotional_bro", fail)
    monkeypatch.setattr(
        Integration,
        "original_image_generation",
        lambda *args: fallback_calls.append(args) or "fallback-url",
    )
    result = call_collection(realtime=True)
    assert fallback_calls[0] == ("Wendy", "高兴 because 收到邀请很开心", "3")
    assert result[3] == "fallback-url"
    assert "Recent_Url:fallback-url" in records.read_text(encoding="utf-8")


def test_tc_res_01_index_eight_advances_to_nine(monkeypatch, tmp_path):
    """TC-RES-01：索引 8 使用 8 号槽并递增到 9。"""
    records, voice_calls = prepare_collection(monkeypatch, tmp_path, index="8")
    result = call_collection()
    assert voice_calls[0][4] == "8"
    assert result[1] == "8"
    assert "index:9" in records.read_text(encoding="utf-8")


def test_tc_res_02_index_nine_wraps_to_zero(monkeypatch, tmp_path):
    """TC-RES-02：索引 9 使用 9 号槽并回绕到 0。"""
    records, voice_calls = prepare_collection(monkeypatch, tmp_path, index="9")
    result = call_collection()
    assert voice_calls[0][4] == "9"
    assert result[1] == "9"
    assert "index:0" in records.read_text(encoding="utf-8")


def test_tc_res_03_missing_records_falls_back_then_write_fails(monkeypatch, tmp_path):
    """TC-RES-03：Records 缺失时先静态降级，随后更新记录失败。"""
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    monkeypatch.chdir(backend_dir)
    voice_calls = []
    static_calls = []
    realtime_calls = []
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: FIXED_REPLY)
    monkeypatch.setattr(
        Integration,
        "Voice_Generation_through_http",
        lambda *args: voice_calls.append(args) or "",
    )
    monkeypatch.setattr(
        Integration, "static_images", lambda *args: static_calls.append(args) or ""
    )
    monkeypatch.setattr(
        Integration, "emotional_bro", lambda *args: realtime_calls.append(args)
    )
    with pytest.raises(FileNotFoundError):
        call_collection(realtime=True)
    assert voice_calls[0][4] == "0"
    assert static_calls == [("Wendy", "mock-image")]
    assert realtime_calls == []


def test_tc_ex_01_missing_role_record_fails_before_external_calls(monkeypatch, tmp_path):
    """TC-EX-01：角色记录缺失时 matches[0] 抛异常且未调用外部服务。"""
    make_workspace(monkeypatch, tmp_path, role="Other")
    calls = []
    monkeypatch.setattr(
        Integration, "get_llm_response", lambda *_args: calls.append("llm")
    )
    with pytest.raises(IndexError):
        call_collection()
    assert calls == []


@pytest.mark.xfail(strict=True, reason="TC-EX-02：正则表达式先排除了非数字索引")
def test_tc_ex_02_nonnumeric_index_fails_after_external_side_effects(monkeypatch, tmp_path):
    """TC-EX-02：按清单预期，非数字索引应在外部副作用之后转换失败。"""
    _assets, records = make_workspace(monkeypatch, tmp_path)
    records.write_text("Wendy:\nRecent_Url:old-url\nindex:abc\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        Integration,
        "get_llm_response",
        lambda *_args: calls.append("llm") or FIXED_REPLY,
    )
    monkeypatch.setattr(
        Integration,
        "Voice_Generation_through_http",
        lambda *_args: calls.append("tts") or "",
    )
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "")
    with pytest.raises(ValueError):
        call_collection()
    assert calls == ["llm", "tts"]


def test_tc_con_01_concurrent_requests_share_same_slot(monkeypatch, tmp_path):
    """TC-CON-01：强制并发交错，验证两个请求读取并使用同一资源槽。"""
    make_workspace(monkeypatch, tmp_path, index="3")
    barrier = Barrier(2)
    voice_slots = []
    updates = []

    def fixed_llm(*_args):
        barrier.wait(timeout=5)
        return FIXED_REPLY

    monkeypatch.setattr(Integration, "get_llm_response", fixed_llm)
    monkeypatch.setattr(
        Integration,
        "Voice_Generation_through_http",
        lambda *_args: voice_slots.append(_args[4]) or "",
    )
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "")
    monkeypatch.setattr(
        Integration,
        "updateLinks",
        lambda role, url, index: updates.append((role, url, index)),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: call_collection(), range(2)))
    assert voice_slots == ["3", "3"]
    assert [result[1] for result in results] == ["3", "3"]
    assert updates == [("Wendy", "", "4"), ("Wendy", "", "4")]
