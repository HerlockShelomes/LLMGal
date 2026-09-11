from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import Integration


def write_records(path: Path, role: str = "Wendy", url: str = "old-url", index: str = "3"):
    path.write_text(
        f"{role}:\nRecent_Url:{url}\nindex:{index}\n", encoding="utf-8"
    )


def prepare_static(monkeypatch, tmp_path, answer="(高兴)(收到邀请)你好", index="3"):
    records = tmp_path / "Records.txt"
    write_records(records, index=index)
    voice_calls = []
    monkeypatch.setattr(Integration, "RECORDS_PATH", records)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: answer)
    monkeypatch.setattr(
        Integration,
        "Voice_Generation_through_http",
        lambda *args: voice_calls.append(args) or "mock.mp3",
    )
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "")
    return records, voice_calls


def test_cfg_04_supported_voice_category_maps_to_expected_voice():
    expected = {
        "GirlFriend": "zh_female_tianxinxiaomei_emo_v2_mars_bigtts",
        "BoyFriend": "zh_male_yourougongzi_emo_v2_mars_bigtts",
        "ElderSister": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
        "LiteratureGuy": "zh_male_ruyayichen_emo_v2_mars_bigtts",
    }
    assert {
        category: Integration.request_confirmation(category, "中性")[0]
        for category in expected
    } == expected


def test_cfg_05_unknown_voice_category_uses_default_voice():
    default_voice = Integration.request_confirmation("GirlFriend", "中性")[0]
    assert Integration.request_confirmation("UnknownVoice", "中性")[0] == default_voice
    assert Integration.request_confirmation("", "中性")[0] == default_voice


def test_llm_03_no_emotion_tags_defaults_to_neutral(monkeypatch, tmp_path):
    _, voice_calls = prepare_static(monkeypatch, tmp_path, answer="普通回复")
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
    )
    assert result[2] == "neutral"
    assert voice_calls[0][2] == "neutral"


def test_llm_04_one_emotion_tag_uses_empty_reason(monkeypatch, tmp_path):
    records, voice_calls = prepare_static(monkeypatch, tmp_path, answer="(悲伤)回复正文")
    image_calls = []
    monkeypatch.setattr(
        Integration,
        "emotional_bro",
        lambda *args: image_calls.append(args) or "new-url",
    )
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", True, {"role": "user", "content": "hi"}
    )
    assert result[2] == "sad"
    assert voice_calls[0][2] == "sad"
    assert image_calls[0][2] == ["悲伤", ""]
    assert "Recent_Url:new-url" in records.read_text(encoding="utf-8")


def test_llm_05_extra_emotion_tags_ignore_tags_after_second(monkeypatch, tmp_path):
    prepare_static(monkeypatch, tmp_path, answer="(惊喜)(因为收到礼物)(额外描述)正文")
    image_calls = []
    monkeypatch.setattr(
        Integration,
        "emotional_bro",
        lambda *args: image_calls.append(args) or "new-url",
    )
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", True, {"role": "user", "content": "hi"}
    )
    assert result[2] == "surprised"
    assert image_calls[0][2] == ["惊喜", "因为收到礼物"]


def test_img_03_realtime_generation_uses_recent_url_and_updates_record(monkeypatch, tmp_path):
    records, _ = prepare_static(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        Integration,
        "emotional_bro",
        lambda *args: calls.append(args) or "new-image-url",
    )
    result = Integration.Response_Collection(
        "model", "high_aes_ip_v20", "Wendy", "ElderSister", True,
        {"role": "user", "content": "hi"},
    )
    assert calls[0][0] == "old-url"
    assert calls[0][3:] == ("3", "high_aes_ip_v20")
    assert result[3] == "new-image-url"
    assert "Recent_Url:new-image-url\nindex:4" in records.read_text(encoding="utf-8")


def test_img_04_realtime_failure_falls_back_to_text_to_image(monkeypatch, tmp_path):
    records, _ = prepare_static(monkeypatch, tmp_path)
    fallback_calls = []

    def fail_realtime(*_args):
        raise RuntimeError("expired URL")

    monkeypatch.setattr(Integration, "emotional_bro", fail_realtime)
    monkeypatch.setattr(
        Integration,
        "original_image_generation",
        lambda *args: fallback_calls.append(args) or "fallback-url",
    )
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", True, {"role": "user", "content": "hi"}
    )
    assert fallback_calls[0][0] == "Wendy"
    assert result[3] == "fallback-url"
    assert "Recent_Url:fallback-url" in records.read_text(encoding="utf-8")


def test_res_01_index_eight_uses_slot_eight_and_advances_to_nine(monkeypatch, tmp_path):
    records, voice_calls = prepare_static(monkeypatch, tmp_path, index="8")
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
    )
    assert voice_calls[0][4] == "8"
    assert result[1] == "8"
    content = records.read_text(encoding="utf-8")
    assert "Recent_Url:old-url" in content and "index:9" in content


def test_res_02_index_nine_wraps_to_zero(monkeypatch, tmp_path):
    records, voice_calls = prepare_static(monkeypatch, tmp_path, index="9")
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
    )
    assert voice_calls[0][4] == "9"
    assert result[1] == "9"
    assert "index:0" in records.read_text(encoding="utf-8")


def test_res_03_missing_records_file_recovers_in_static_mode(monkeypatch, tmp_path):
    records = tmp_path / "missing" / "Records.txt"
    realtime_calls = []
    monkeypatch.setattr(Integration, "RECORDS_PATH", records)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: "普通回复")
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *_args: "")
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "static-url")
    monkeypatch.setattr(
        Integration, "emotional_bro", lambda *_args: realtime_calls.append(True)
    )
    result = Integration.Response_Collection(
        "model", "image", "Wendy", "ElderSister", True, {"role": "user", "content": "hi"}
    )
    assert realtime_calls == []
    assert result[1] == "0"
    assert records.read_text(encoding="utf-8") == (
        "Wendy:\nRecent_Url:static-url\nindex:1\n"
    )


def test_ex_01_missing_role_record_fails_before_external_calls_with_controlled_error(monkeypatch, tmp_path):
    records = tmp_path / "Records.txt"
    write_records(records, role="Other")
    monkeypatch.setattr(Integration, "RECORDS_PATH", records)
    external_calls = []
    monkeypatch.setattr(
        Integration, "get_llm_response", lambda *_args: external_calls.append(True)
    )
    with pytest.raises(Integration.RecordStateError, match="不存在角色"):
        Integration.Response_Collection(
            "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
        )
    assert external_calls == []


def test_ex_02_nonnumeric_index_fails_before_external_calls_with_controlled_error(monkeypatch, tmp_path):
    records = tmp_path / "Records.txt"
    write_records(records, index="abc")
    monkeypatch.setattr(Integration, "RECORDS_PATH", records)
    external_calls = []
    monkeypatch.setattr(
        Integration, "get_llm_response", lambda *_args: external_calls.append(True)
    )
    with pytest.raises(Integration.RecordStateError, match="0 到 9"):
        Integration.Response_Collection(
            "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
        )
    assert external_calls == []


def test_con_01_concurrent_same_role_requests_use_distinct_slots(monkeypatch, tmp_path):
    records, voice_calls = prepare_static(monkeypatch, tmp_path, index="3")

    def invoke():
        return Integration.Response_Collection(
            "model", "image", "Wendy", "ElderSister", False, {"role": "user", "content": "hi"}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: invoke(), range(2)))
    assert {result[1] for result in results} == {"3", "4"}
    assert {call[4] for call in voice_calls} == {"3", "4"}
    assert "index:5" in records.read_text(encoding="utf-8")
