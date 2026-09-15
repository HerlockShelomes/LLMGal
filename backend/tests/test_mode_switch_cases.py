"""运行时模式（Mock / 正式版）切换的隔离用例。

覆盖三件事：
1. 开关本身：默认值、落盘后能被重新读取（跨进程的等价物）、非法取值被拒、REST 往返；
2. 一致性：手工改开关文件、或另一个 worker 进程写入，都不能出现「界面与后端各说各话」；
3. Mock 版的语义：AI 一个都不调、回复/音频/图像三段被固定、Records 不被污染、
   音频写进 voice/_mock/ 而不是正式版槽位；
4. 模式随响应下发（payload.mode）—— 前端据此选择音频目录，不必（也不能）靠
   「界面上的当前模式」去猜，否则切换发生在两次回复之间时必然错配。

所有用例都不触碰真实外部服务（conftest 的 autouse fixture 会把漏掉的调用判失败）。
conftest 已把测试期模式钉死为 prod，所以需要 mock 的用例都显式调用 force_mode()。
"""

from __future__ import annotations

import json
import os

import pytest

import config
import Connect
import Integration
import MockMode


def force_mode(monkeypatch, tmp_path, mode: str) -> str:
    """写入开关文件并把 MODE_PATH 指过去。

    刻意走真实的读盘路径，而不是 monkeypatch 掉 get_mode/is_mock ——
    否则测的是替身，不是被测代码。
    """
    path = tmp_path / "runtime_mode.json"
    path.write_text(json.dumps({"mode": mode}), encoding="utf-8")
    monkeypatch.setattr(config, "MODE_PATH", str(path))
    return str(path)


def isolate_mode_state(monkeypatch, tmp_path) -> str:
    """把开关文件指到不存在的临时路径，并把默认值钉成 prod（= 从未切换过）。"""
    path = tmp_path / "runtime_mode.json"
    monkeypatch.setattr(config, "MODE_PATH", str(path))
    monkeypatch.setattr(config, "_initial_mode", config.MODE_PROD)
    return str(path)


@pytest.fixture
def mock_assets(monkeypatch, tmp_path):
    """搭一份最小 assets 结构并切到该 cwd（MockMode 按 backend 相对路径读写）。

    刻意只放「本地已存在」的测试音频与 neutral 图 —— MockMode 只允许复制，
    不允许现场合成或出图，缺什么就该如实降级。
    """
    backend_dir = tmp_path / "backend"
    voice_dir = tmp_path / "frontend" / "src" / "assets" / "voice" / "Wendy"
    picture_dir = tmp_path / "frontend" / "src" / "assets" / "pictures" / "Wendy"
    backend_dir.mkdir(exist_ok=True)
    voice_dir.mkdir(parents=True)
    picture_dir.mkdir(parents=True)
    (voice_dir / "Wendy_test_Stream.wav").write_bytes(b"FAKE-WAV-BYTES")
    (picture_dir / "Wendy_neutral.jpg").write_bytes(b"FAKE-JPG")
    monkeypatch.chdir(backend_dir)
    return tmp_path, voice_dir, picture_dir


def call_collection(realtime=False, text="你好"):
    return Integration.Response_Collection(
        "mock-model", "mock-image", "Wendy", "ElderSister", realtime, text,
    )


# ---------------------------------------------------------------------------
# 开关本身
# ---------------------------------------------------------------------------
def test_tc_mode_01_defaults_to_prod_when_no_state_file(monkeypatch, tmp_path):
    """TC-MODE-01：没有任何落盘记录时默认正式版，不会静默降级成 mock。"""
    isolate_mode_state(monkeypatch, tmp_path)
    assert config.get_mode() == config.MODE_PROD
    assert not config.is_mock()
    assert "正式版" in config.mode_label()


def test_tc_mode_02_switch_persists_and_is_re_read(monkeypatch, tmp_path):
    """TC-MODE-02：切换落盘；读取只认文件，手工改动/另一个进程写入也立即生效。"""
    path = isolate_mode_state(monkeypatch, tmp_path)

    assert config.set_mode("mock") == config.MODE_MOCK
    assert json.loads(open(path, encoding="utf-8").read())["mode"] == config.MODE_MOCK

    # 默认值反向钉成 prod：若 get_mode() 走的是进程内残留状态或默认值，
    # 这里会返回 prod。断言它读到的是文件 —— 即「重启 / 另一个 worker」的等价物。
    monkeypatch.setattr(config, "_initial_mode", config.MODE_PROD)
    assert config.get_mode() == config.MODE_MOCK
    assert config.is_mock()
    assert "Mock" in config.mode_label()

    # 反向：直接编辑开关文件（运维排障常见做法）也必须立刻生效
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"mode": "prod"}, file)
    assert config.get_mode() == config.MODE_PROD
    assert not config.is_mock()


def test_tc_mode_03_rejects_unknown_value(monkeypatch, tmp_path):
    """TC-MODE-03：非法取值抛 ValueError，不产生落盘副作用。"""
    path = isolate_mode_state(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        config.set_mode("production")
    assert not os.path.exists(path)
    assert config.get_mode() == config.MODE_PROD


def test_tc_mode_04_rest_endpoints_round_trip(monkeypatch, tmp_path):
    """TC-MODE-04：REST 切换与查询接口往返一致。"""
    isolate_mode_state(monkeypatch, tmp_path)

    assert Connect.api_get_mode()["mode"] == config.MODE_PROD

    payload = Connect.api_set_mode(Connect.ModeRequest(mode="mock"))
    assert payload["status"] == "ok"
    assert payload["mock"] is True
    assert Connect.api_get_mode()["mock"] is True

    Connect.api_set_mode(Connect.ModeRequest(mode="prod"))
    assert Connect.api_get_mode()["mode"] == config.MODE_PROD
    assert Connect.api_get_mode()["mock"] is False


def test_tc_mode_05_rest_rejects_unknown_value():
    """TC-MODE-05：REST 层把非法取值翻成 400。"""
    response = Connect.api_set_mode(Connect.ModeRequest(mode="???"))
    assert response.status_code == 400


def test_tc_mode_06_missing_credentials_silent_in_mock_mode(monkeypatch, tmp_path):
    """TC-MODE-06：Mock 版不调厂商接口，缺密钥不该被报成故障。"""
    force_mode(monkeypatch, tmp_path, config.MODE_MOCK)
    assert config.missing_credentials() == []


def test_tc_mode_07_persist_failure_is_not_reported_as_success(monkeypatch, tmp_path):
    """TC-MODE-07：落盘失败必须抛错，不能静默返回「切换成功」。

    把 MODE_PATH 指到一个已存在的目录：临时文件能写出，但末尾的 os.replace
    必然失败 —— 用一个真实会失败的场景，而不是打桩 os.replace。
    """
    monkeypatch.setattr(config, "MODE_PATH", str(tmp_path))
    monkeypatch.setattr(config, "_initial_mode", config.MODE_PROD)

    with pytest.raises(RuntimeError):
        config.set_mode("mock")
    assert config.get_mode() == config.MODE_PROD


def test_tc_mode_08_rest_translates_persist_failure(monkeypatch, tmp_path):
    """TC-MODE-08：落盘失败在 REST 层翻成 500，而不是回 200 谎报成功。"""
    monkeypatch.setattr(config, "MODE_PATH", str(tmp_path))
    monkeypatch.setattr(config, "_initial_mode", config.MODE_PROD)

    response = Connect.api_set_mode(Connect.ModeRequest(mode="mock"))

    assert response.status_code == 500
    assert config.get_mode() == config.MODE_PROD


# ---------------------------------------------------------------------------
# Mock 版的语义
# ---------------------------------------------------------------------------
def test_tc_mode_09_mock_bypasses_every_vendor_call(monkeypatch, mock_assets):
    """TC-MODE-09：mock 下 LLM/TTS/图像全部不被调用，且不碰 Records。"""
    workdir, _voice_dir, _picture_dir = mock_assets
    force_mode(monkeypatch, workdir, config.MODE_MOCK)

    def blocked(*_args, **_kwargs):
        raise AssertionError("Mock 版不允许调用厂商接口")

    monkeypatch.setattr(Integration, "get_llm_response", blocked)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", blocked)
    monkeypatch.setattr(Integration, "static_images", blocked)
    monkeypatch.setattr(Integration, "emotional_bro", blocked)
    monkeypatch.setattr(Integration, "original_image_generation", blocked)

    answer, index, emotion, url, status = call_collection(text="帮我写一首关于秋天的诗")

    assert emotion == MockMode.FIXED_EMOTION == "neutral"
    assert index == MockMode.FIXED_INDEX == "0"
    assert url == "", "mock 不生成图片，imageUrl 必须为空"
    assert status == "success"
    # 回执要能反映这一次请求，而不是一段与输入无关的死文案
    assert "帮我写一首关于秋天的诗" in answer
    assert "已旁路" in answer
    # 没建过 Records.txt：mock 不该推进正式版的资源轮转
    assert not (workdir / "frontend" / "src" / "assets" / "Records.txt").exists()


def test_tc_mode_10_mock_pins_audio_to_isolated_slot(monkeypatch, mock_assets):
    """TC-MODE-10：音频固定且**写到 mock 专属目录**，正式版槽位一个字节都不动。

    隔离目录是这次改动的重点：以前 mock 直接覆盖 voice/{角色}/{角色}_0_Stream.wav，
    等于往正式版的工作区里塞测试音频 —— 切回正式版后回看同 index 的历史消息会播错，
    而且「mock 的 index 0」与「正式的 index 0」指向同一份文件，事后无法区分。
    """
    workdir, voice_dir, _picture_dir = mock_assets
    force_mode(monkeypatch, workdir, config.MODE_MOCK)

    # 先摆一个"正式版已经用过 index 0"的槽位，证明 mock 连覆盖都不会发生
    prod_slot = voice_dir / f"Wendy_{MockMode.FIXED_INDEX}_Stream.wav"
    prod_slot.write_bytes(b"REAL-CONVERSATION-AUDIO")

    first = call_collection()

    # 实际落点是 voice/_mock/{角色}/，voice_dir 本身是 voice/{角色}/
    mock_dir = voice_dir.parent / MockMode.MOCK_VOICE_DIRNAME
    mock_slot = mock_dir / "Wendy" / "Wendy_0_Stream.wav"
    assert mock_slot.read_bytes() == b"FAKE-WAV-BYTES"

    # 正式版目录必须保持原样：那条真实对话音频一个字节都不能被改写
    assert prod_slot.read_bytes() == b"REAL-CONVERSATION-AUDIO"

    # 第二轮：同一份内容再落一次，路径与内容都不变
    second = call_collection(text="换个问题")
    assert first[1] == second[1] == MockMode.FIXED_INDEX
    assert mock_slot.read_bytes() == b"FAKE-WAV-BYTES"
    assert first[4] == second[4] == "success"
    assert prod_slot.read_bytes() == b"REAL-CONVERSATION-AUDIO"


def test_tc_mode_11_mock_degrades_to_partial_without_local_audio(monkeypatch, mock_assets):
    """TC-MODE-11：本地无测试音频时降级为 partial，绝不偷偷去合成。"""
    workdir, voice_dir, _picture_dir = mock_assets
    (voice_dir / "Wendy_test_Stream.wav").unlink()
    force_mode(monkeypatch, workdir, config.MODE_MOCK)

    answer, _index, _emotion, _url, status = call_collection()

    assert status == "partial"
    assert "不调用 TTS" in answer
    # 无源时连隔离目录都不该建出来
    assert not (voice_dir.parent / MockMode.MOCK_VOICE_DIRNAME).exists()


def test_tc_mode_12_ai_endpoints_blocked_in_mock_mode(monkeypatch, tmp_path):
    """TC-MODE-12：mock 下「生成形象 / 创建角色」被明确拦下（409），不是静默降级。"""
    force_mode(monkeypatch, tmp_path, config.MODE_MOCK)

    image_resp = Connect.api_generate_image(
        Connect.GenerateImageRequest(roleName="新角色")
    )
    assert image_resp.status_code == 409

    role_resp = Connect.api_create_role(
        Connect.CreateRoleRequest(roleName="新角色", personality="安静")
    )
    assert role_resp.status_code == 409


def test_tc_mode_13_prod_mode_keeps_real_pipeline(monkeypatch, mock_assets):
    """TC-MODE-13：切回正式版后走真实链路（此处以 stub 验证被调用）。"""
    workdir, _voice_dir, _picture_dir = mock_assets
    force_mode(monkeypatch, workdir, config.MODE_PROD)

    calls = []
    monkeypatch.setattr(
        Integration, "get_llm_response",
        lambda *args, **kwargs: calls.append("llm") or "(高兴)(收到邀请很开心)你好呀",
    )
    monkeypatch.setattr(
        Integration, "Voice_Generation_through_http",
        lambda *args: calls.append("tts") or "fixed-audio.wav",
    )
    monkeypatch.setattr(Integration, "static_images", lambda *_args: "")

    answer, _index, emotion, _url, status = call_collection()

    assert calls == ["llm", "tts"]
    assert emotion == "happy"
    assert "AI 未接入" not in answer
    assert status == "success"


def test_tc_mode_14_response_carries_its_own_mode(monkeypatch, mock_assets):
    """TC-MODE-14：响应自带产出它的模式，前端不必也不该去猜。

    这是「音频目录按模式分流」的前端前提：前端拿 payload.mode 决定去
    voice/_mock/{角色}/ 还是 voice/{角色}/。若这一项缺失，前端只能退回用
    界面上的当前模式推断，切换时序一对不上就会取到另一个目录的音频。
    """
    workdir, _voice_dir, _picture_dir = mock_assets
    force_mode(monkeypatch, workdir, config.MODE_MOCK)

    request = Connect.ClientRequest(
        textModel_config={"text": "你好", "modelText": "mock-model"},
        role="Wendy",
        imageModel_config={"modelImage": "mock-image", "realTimeRendering": False},
        voiceCate="ElderSister",
        history=[],
        sessionId="session-mode-14",
    )
    assert Connect.process_query(request).mode == config.MODE_MOCK

    # 缺省值即 prod：老后端不带 mode 时，前端应回到改动前的行为
    assert Connect.ServerResponse(
        response="", emotion="", index="0", metrics={}, imageUrl=""
    ).mode == config.MODE_PROD
