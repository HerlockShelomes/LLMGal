"""针对本轮「前后端连通 + AI 接入」改造新增的用例。

覆盖的缺陷：N02/N03/N04/N01/009/B07/B05/B02，以及多轮上下文、
provider 分发、WebSocket 控制帧与鉴权等新增能力。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

import Connect
import Image
import Integration
import Text
import Voice
import config


FIXED_REPLY = "(高兴)(收到邀请很开心)你好呀"


# ---------------------------------------------------------------------------
# 通用脚手架
# ---------------------------------------------------------------------------
def make_workspace(monkeypatch, tmp_path: Path, *, role="Wendy", index="3", url="old-url"):
    backend_dir = tmp_path / "backend"
    assets = tmp_path / "frontend" / "src" / "assets"
    backend_dir.mkdir(exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    records = assets / "Records.txt"
    records.write_text(f"{role}:\nRecent_Url:{url}\nindex:{index}\n", encoding="utf-8")
    monkeypatch.chdir(backend_dir)
    return assets, records


def call_collection(*, realtime=False, image_model="mock-image", history=None):
    return Integration.Response_Collection(
        "mock-model", image_model, "Wendy", "ElderSister", realtime,
        {"role": "user", "content": "你好"}, history,
    )


class FakeResponse:
    def __init__(self, content: bytes = b"", content_type: str = "audio/mpeg",
                 payload: dict | None = None):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeWebSocket:
    """最小 WebSocket 替身，支持 query_params 与 close。"""

    def __init__(self, incoming=None, query_params=None, headers=None):
        self.incoming = list(incoming or [])
        self.sent = []
        self.accepted = False
        self.closed = False
        self.client_state = WebSocketState.CONNECTED
        self.query_params = query_params or {}
        self.headers = headers or {}

    async def accept(self):
        self.accepted = True

    def _pop(self):
        if not self.incoming:
            self.client_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(code=1000)
        item = self.incoming.pop(0)
        return item if isinstance(item, str) else json.dumps(item)

    async def receive_text(self):
        return self._pop()

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True


async def run_socket(incoming, monkeypatch, *, response=None, query_params=None, headers=None):
    websocket = FakeWebSocket(incoming, query_params, headers)
    if response is not None:
        monkeypatch.setattr(Connect, "process_query", lambda *_args, **_kwargs: response)
    await Connect.websocket_chat(websocket)
    return websocket


def fixed_response() -> Connect.ServerResponse:
    return Connect.ServerResponse(
        response=FIXED_REPLY, emotion="happy", index="3",
        metrics={"time_cost": 0.01, "tokens_used": 10}, imageUrl="",
    )


# ---------------------------------------------------------------------------
# 文本层：N02 / N03 / 多轮上下文
# ---------------------------------------------------------------------------
def test_n02_role_prompt_uses_system_role(monkeypatch, tmp_path):
    """N02：人设必须由 system 承载。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    roles = assets / "roles"
    roles.mkdir()
    (roles / "Wendy.txt").write_text("固定角色描述", encoding="utf-8")

    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return []

    client = type("C", (), {"chat": type("D", (), {"completions": Completions()})})()
    monkeypatch.setattr(Text, "OpenAI", lambda **_kwargs: client)
    Text.get_llm_response("mock-model", "Wendy", {"role": "user", "content": "你好"})
    assert captured["messages"][0]["role"] == "system"


def test_n03_missing_role_prompt_raises(monkeypatch, tmp_path):
    """N03：人设文件缺失时明确报错，不再静默发空 prompt。"""
    make_workspace(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        Text.get_role_prompt("NotExistRole")


def test_unknown_text_model_falls_back_to_env(monkeypatch):
    """前端残留旧中转站 ID（deepseek-ai/DeepSeek-V3）时不能直接打挂请求。

    该 ID 在智谱不存在，原样转发会 1211「模型不存在」，整轮对话失败。
    """
    monkeypatch.setattr(config, "TEXT_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "TEXT_MODEL", "env-model")
    monkeypatch.setattr(config, "TEXT_MODEL_ALLOWLIST", {"env-model", "glm-5.3-flash"})
    assert config.resolve_text_model("deepseek-ai/DeepSeek-V3") == "env-model"


def test_text_model_resolution_matrix(monkeypatch):
    """白名单内的模型放行；空值走 .env；custom provider 原样放行。"""
    monkeypatch.setattr(config, "TEXT_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "TEXT_MODEL", "env-model")
    monkeypatch.setattr(config, "TEXT_MODEL_ALLOWLIST", {"env-model", "glm-5.3-flash"})

    assert config.resolve_text_model("glm-5.3-flash") == "glm-5.3-flash"
    assert config.resolve_text_model("") == "env-model"
    assert config.resolve_text_model(None) == "env-model"

    monkeypatch.setattr(config, "TEXT_PROVIDER", "custom")
    assert config.resolve_text_model("whatever-local-model") == "whatever-local-model"


def test_llm_request_uses_resolved_model(monkeypatch, tmp_path):
    """真实请求里发出去的必须是收敛后的模型名。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    (assets / "roles").mkdir()
    (assets / "roles" / "Wendy.txt").write_text("固定角色描述", encoding="utf-8")

    monkeypatch.setattr(config, "TEXT_PROVIDER", "zhipu")
    monkeypatch.setattr(config, "TEXT_MODEL", "env-model")
    monkeypatch.setattr(config, "TEXT_MODEL_ALLOWLIST", {"env-model"})

    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return []

    client = type("C", (), {"chat": type("D", (), {"completions": Completions()})})()
    monkeypatch.setattr(Text, "OpenAI", lambda **_kwargs: client)

    Text.get_llm_response("deepseek-ai/DeepSeek-V3", "Wendy",
                          {"role": "user", "content": "你好"})
    assert captured["model"] == "env-model"


def test_history_is_forwarded_to_llm(monkeypatch, tmp_path):
    """多轮上下文：history 必须透传给模型。"""
    make_workspace(monkeypatch, tmp_path)
    seen = {}

    def fake_llm(model, role, prompt, history=None, on_reasoning=None):
        seen["history"] = history
        return FIXED_REPLY

    monkeypatch.setattr(Integration, "get_llm_response", fake_llm)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "ok.mp3")
    monkeypatch.setattr(Integration, "static_images", lambda *a: "")
    history = [{"role": "user", "content": "上上句"}, {"role": "assistant", "content": "上句"}]
    call_collection(history=history)
    assert seen["history"] == history


def test_sanitize_history_filters_invalid_entries():
    """历史清洗：丢弃非法条目并限制长度。"""
    cleaned = Text.sanitize_history([
        {"role": "user", "content": "有效"},
        {"role": "system", "content": "应被丢弃"},
        "not-a-dict",
        {"role": "assistant", "content": "   "},
    ])
    assert cleaned == [{"role": "user", "content": "有效"}]


def test_normalize_message_accepts_plain_string():
    """兼容早期前端直接发字符串的情况。"""
    assert Text.normalize_message("你好") == {"role": "user", "content": "你好"}
    assert Text.normalize_message({"role": "assistant", "content": "hi"}) == {
        "role": "assistant", "content": "hi"}


# ---------------------------------------------------------------------------
# 语音层：N04 / provider 分发
# ---------------------------------------------------------------------------
def test_n04_emotion_brackets_are_stripped_before_tts():
    """N04：送进 TTS 的文本不应包含开头的情绪括号。"""
    assert Voice.strip_emotion_tags("(高兴)(因为受到邀请)你好呀") == "你好呀"
    # 正文中间的括号要保留
    assert Voice.strip_emotion_tags("(高兴)他说(小声)了一句") == "他说(小声)了一句"


def test_tts_qwen_provider_saves_audio(monkeypatch, tmp_path):
    """Qwen3-TTS（免费档）：官方端点返回音频 URL，需二次下载并落盘为 wav。

    这个用例锁住三个易错点：端点不是 OpenAI 的 /audio/speech；
    data 字段是空的、音频在 output.audio.url；返回的是 WAV 不是 MP3。
    """
    assets, _records = make_workspace(monkeypatch, tmp_path)
    captured = {}

    def post(**kwargs):
        captured.update(kwargs)
        return FakeResponse(
            content_type="application/json",
            payload={"output": {"audio": {"url": "http://example.com/a.wav"}},
                     "usage": {"characters": 10}},
        )

    def get(**kwargs):
        captured.setdefault("download", kwargs)
        return FakeResponse(content=b"fixed-wav-bytes", content_type="audio/wav")

    monkeypatch.setattr(Voice.requests, "post", post)
    monkeypatch.setattr(Voice.requests, "get", get)
    result = Voice.Voice_Generation_through_http(
        "Wendy", "zh_female_tianxinxiaomei_emo_v2_mars_bigtts", "happy", "你好", "3",
        provider="qwen",
    )
    assert result.endswith("Wendy_3_Stream.wav")
    assert (assets / "voice" / "Wendy" / "Wendy_3_Stream.wav").read_bytes() == b"fixed-wav-bytes"
    assert captured["json"]["input"]["text"] == "你好"
    # Wendy 在 config.ROLE_VOICES 里登记的是 Serena（每个角色一个音色），
    # 它的优先级高于「火山音色 ID -> Qwen 音色」的兜底映射（那才会落到 Cherry）。
    # 想验证兜底映射本身请看下面那个不传角色的用例。
    assert captured["json"]["input"]["voice"] == "Serena"
    assert "generation" in captured["url"]


def test_tts_provider_default_is_configurable(monkeypatch, tmp_path):
    """未显式指定 provider 时，跟随 config.TTS_PROVIDER。"""
    make_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        Voice.requests, "post",
        lambda **_k: FakeResponse(
            content_type="application/json",
            payload={"output": {"audio": {"url": "http://example.com/a.wav"}}}),
    )
    monkeypatch.setattr(
        Voice.requests, "get",
        lambda **_k: FakeResponse(content=b"x", content_type="audio/wav"),
    )
    monkeypatch.setattr(Voice.config, "TTS_PROVIDER", "qwen")
    assert Voice.Voice_Generation_through_http("Wendy", "v", "neutral", "你好", "3")


# ---------------------------------------------------------------------------
# 编排层：009 / B07 / N01
# ---------------------------------------------------------------------------
def test_009_tts_failure_downgrades_status_to_partial(monkeypatch, tmp_path):
    """缺陷 009：TTS 失败不能再谎报 success。"""
    make_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *a, **_kwargs: FIXED_REPLY)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "")
    monkeypatch.setattr(Integration, "static_images", lambda *a: "")
    result = call_collection()
    assert result[4] == "partial"


def test_success_flow_reports_success(monkeypatch, tmp_path):
    """全部成功时状态为 success。"""
    make_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *a, **_kwargs: FIXED_REPLY)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "ok.mp3")
    monkeypatch.setattr(Integration, "static_images", lambda *a: "")
    assert call_collection()[4] == "success"


def test_b07_empty_image_url_must_not_clear_recent_url(monkeypatch, tmp_path):
    """缺陷 B07：没有新图时，Records 里已有的 Recent_Url 不能被空串覆盖。"""
    _assets, records = make_workspace(monkeypatch, tmp_path, url="old-url")
    monkeypatch.setattr(Integration, "get_llm_response", lambda *a, **_kwargs: FIXED_REPLY)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "ok.mp3")
    monkeypatch.setattr(Integration, "static_images", lambda *a: "")
    result = call_collection()
    # 前端拿到的是"本次无新图"（空串），但落盘的 Recent_Url 必须保留旧值
    assert result[3] == ""
    assert "Recent_Url:old-url" in records.read_text(encoding="utf-8")


def test_n01_update_links_runs_inside_role_lock(monkeypatch, tmp_path):
    """缺陷 N01：Records 写回必须在角色锁内完成。

    若在锁外执行，并发下两个请求会各自读到旧值再互相覆盖，index 会回退、
    不同请求会复用同一个资源槽位并覆盖彼此的图片与语音。
    """
    make_workspace(monkeypatch, tmp_path)
    lock_states = []
    real_lock = Integration._lock_for("Wendy")

    monkeypatch.setattr(Integration, "get_llm_response", lambda *a, **_kwargs: FIXED_REPLY)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "ok.mp3")
    monkeypatch.setattr(Integration, "static_images", lambda *a: "")

    def spy(role, url, index):
        # updateLinks 被调用的瞬间，角色锁应当处于「已被当前线程持有」的状态
        lock_states.append(real_lock.locked())

    monkeypatch.setattr(Integration, "updateLinks", spy)
    call_collection()
    # 若把 updateLinks 移回锁外，这里会变成 [False]
    assert lock_states == [True]


def test_image_failure_downgrades_status(monkeypatch, tmp_path):
    """图片生成整体失败时同样降级为 partial。"""
    make_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *a, **_kwargs: FIXED_REPLY)
    monkeypatch.setattr(Integration, "Voice_Generation_through_http", lambda *a: "ok.mp3")

    def boom(*_args):
        raise RuntimeError("fixed image failure")

    monkeypatch.setattr(Integration, "static_images", boom)
    assert call_collection()[4] == "partial"


# ---------------------------------------------------------------------------
# 图像层：B05
# ---------------------------------------------------------------------------
def test_b05_only_missing_images_are_generated(monkeypatch, tmp_path):
    """缺陷 B05：只补生成缺失的图片，不重生成整套 7 张。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    role_dir = assets / "pictures" / "Wendy"
    role_dir.mkdir(parents=True)
    # 只准备 neutral 一张，其余 6 张缺失
    (role_dir / "Wendy_neutral.jpg").write_bytes(b"fixed")

    calls = []
    monkeypatch.setattr(
        Image, "original_image_generation",
        lambda *args: calls.append(("orig", args)) or "url",
    )
    monkeypatch.setattr(
        Image, "emotional_bro",
        lambda *args: calls.append(("emo", args)) or "url",
    )
    Image.static_images("Wendy", "mock-image")
    # neutral 已存在，只补 6 张；且基准图缺失时走文生图 + 图生图组合
    assert len(calls) <= 6


def test_image_generation_uses_openai_compatible_endpoint(monkeypatch, tmp_path):
    """免费档（CogView）走 OpenAI 兼容 HTTP，无需厂商 SDK。"""
    assets, _records = make_workspace(monkeypatch, tmp_path)
    desc_dir = assets / "pictures" / "Role_Description"
    desc_dir.mkdir(parents=True)
    (desc_dir / "Wendy.txt").write_text(
        "Subject Description: a girl\nAppearance Details: long hair", encoding="utf-8")
    captured = {}

    def post(**kwargs):
        captured.update(kwargs)
        return FakeResponse(
            content_type="application/json",
            payload={"data": [{"url": "https://example.com/a.jpg"}]},
        )

    monkeypatch.setattr(Image.requests, "post", post)
    monkeypatch.setattr(Image, "save_image_from_url", lambda *a: True)
    monkeypatch.setattr(Image.config, "IMAGE_PROVIDER", "zhipu")
    monkeypatch.setattr(Image.config, "IMAGE_ZHIPU_API_KEY", "fixed-key")
    url = Image.original_image_generation("Wendy", "smiling", "happy")
    assert url == "https://example.com/a.jpg"
    assert captured["json"]["model"] == Image.config.IMAGE_ZHIPU_MODEL
    assert "Authorization" in captured["headers"]


def test_resolve_qwen_voice_maps_known_voices():
    """火山音色 ID 需映射到 Qwen3-TTS 音色名。"""
    assert Voice.resolve_qwen_voice("zh_female_tianxinxiaomei_emo_v2_mars_bigtts") == "Cherry"
    assert Voice.resolve_qwen_voice("zh_male_yourougongzi_emo_v2_mars_bigtts") == "Ethan"
    # 未知音色回退到默认音色，不能返回空串
    assert Voice.resolve_qwen_voice("unknown-voice") == Voice.config.TTS_QWEN_DEFAULT_VOICE


def _frame(message_type: int, flags: int, payload: bytes,
           serialization: int = 1, compression: int = 0) -> bytes:
    """构造火山 TTS 二进制协议帧。"""
    header = bytes([
        (1 << 4) | 1,                              # 版本 1 + header size 1
        (message_type << 4) | flags,
        (serialization << 4) | compression,
        0x00,
    ])
    return header + payload


def test_parse_response_writes_audio_and_reports_done(tmp_path):
    """音频帧：写入数据，序列号为负表示结束。"""
    audio_path = tmp_path / "a.mp3"
    with open(audio_path, "wb") as file:
        # 中间帧：seq=0
        payload = (0).to_bytes(4, "big", signed=True) + (2).to_bytes(4, "big") + b"\x01\x02"
        assert Voice.parse_response(_frame(0xB, 1, payload), file) is False
        # 结束帧：seq=-1
        payload = (-1).to_bytes(4, "big", signed=True) + (1).to_bytes(4, "big") + b"\x03"
        assert Voice.parse_response(_frame(0xB, 1, payload), file) is True
    assert audio_path.read_bytes() == b"\x01\x02\x03"


def test_parse_response_ack_frame_without_sequence(tmp_path):
    """无序列号的 ACK 帧：不写数据，返回 False。"""
    audio_path = tmp_path / "b.mp3"
    with open(audio_path, "wb") as file:
        assert Voice.parse_response(_frame(0xB, 0, b""), file) is False
    assert audio_path.read_bytes() == b""


def test_parse_response_error_frame_ends_stream(tmp_path):
    """错误帧：解析出错误码后结束。"""
    audio_path = tmp_path / "c.mp3"
    with open(audio_path, "wb") as file:
        payload = (3001).to_bytes(4, "big") + (5).to_bytes(4, "big") + b"boom!"
        assert Voice.parse_response(_frame(0xF, 1, payload), file) is True


def test_parse_response_frontend_frame(tmp_path):
    """前端帧：仅打印，不视为结束。"""
    audio_path = tmp_path / "d.mp3"
    with open(audio_path, "wb") as file:
        payload = (4).to_bytes(4, "big") + b"info"
        assert Voice.parse_response(_frame(0xC, 1, payload), file) is None


# ---------------------------------------------------------------------------
# WebSocket 层：控制帧 / 鉴权 / 语义校验
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_heartbeat_returns_pong_without_error(monkeypatch):
    websocket = await run_socket([{"type": "heartbeat", "message_id": "h1"}], monkeypatch)
    assert websocket.sent[0]["type"] == "pong"


@pytest.mark.asyncio
async def test_canceled_request_is_not_reported_as_error(monkeypatch):
    websocket = await run_socket(
        [{"type": "canceled_request", "message_id": "c1"}], monkeypatch
    )
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_b02_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setattr(Connect.config, "WS_AUTH_TOKEN", "secret")
    websocket = await run_socket([], monkeypatch, query_params={"token": "wrong"})
    assert websocket.sent[0]["code"] == "AUTH_403"
    assert websocket.closed


@pytest.mark.asyncio
async def test_b02_correct_token_is_accepted(monkeypatch):
    monkeypatch.setattr(Connect.config, "WS_AUTH_TOKEN", "secret")
    websocket = await run_socket(
        [{"type": "heartbeat", "message_id": "h1"}], monkeypatch,
        query_params={"token": "secret"},
    )
    assert websocket.sent[0]["type"] == "pong"


def test_validate_payload_rejects_bad_content():
    assert Connect._validate_payload({"textModel_config": {}, "imageModel_config": {}})
    assert Connect._validate_payload(
        {"textModel_config": {"text": "x"}, "imageModel_config": {}, "history": "nope"})
    assert Connect._validate_payload(
        {"textModel_config": {"text": "x"}, "imageModel_config": {},
         "history": [{"no_content": 1}]})


def test_validate_payload_accepts_valid_payload():
    assert Connect._validate_payload(
        {"textModel_config": {"text": {"role": "user", "content": "hi"}},
         "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
         "history": [{"role": "user", "content": "hi"}]}) == ""


@pytest.mark.asyncio
async def test_invalid_payload_content_returns_invalid_message(monkeypatch):
    message = {
        "type": "client_query",
        "message_id": "m1",
        "payload": {
            "textModel_config": {"modelText": "m"},  # 缺 text
            "role": "Wendy",
            "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
            "voiceCate": "GirlFriend",
        },
    }
    websocket = await run_socket([message], monkeypatch)
    assert websocket.sent[0]["type"] == "invalid_message"
    assert websocket.sent[0]["payload"]["reason"]


@pytest.mark.asyncio
async def test_process_query_runs_off_the_event_loop(monkeypatch):
    """B03：处理逻辑卸载到线程池，不再阻塞事件循环。"""
    import threading
    thread_names = []

    def blocking(*_args, **_kwargs):
        thread_names.append(threading.current_thread().name)
        return fixed_response()

    monkeypatch.setattr(Connect, "process_query", blocking)
    websocket = await run_socket(
        [{"type": "client_query", "message_id": "m1",
          "payload": {"textModel_config": {"text": {"role": "user", "content": "hi"},
                                           "modelText": "m"},
                      "role": "Wendy",
                      "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
                      "voiceCate": "GirlFriend"}},
         {"message_id": "m1"}],
        monkeypatch,
    )
    assert websocket.sent[0]["type"] == "assistant_response"
    # 在线程池里执行，线程名不会是 MainThread
    assert thread_names and thread_names[0] != "MainThread"


@pytest.mark.asyncio
async def test_partial_status_is_forwarded_to_frontend(monkeypatch):
    response = fixed_response()
    response.status = "partial"
    websocket = await run_socket(
        [{"type": "client_query", "message_id": "m1",
          "payload": {"textModel_config": {"text": {"role": "user", "content": "hi"},
                                           "modelText": "m"},
                      "role": "Wendy",
                      "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
                      "voiceCate": "GirlFriend"}},
         {"message_id": "m1"}],
        monkeypatch, response=response,
    )
    assert websocket.sent[0]["status"] == "partial"
