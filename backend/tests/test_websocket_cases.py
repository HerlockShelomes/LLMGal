from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

import Connect
import Image
import Integration


FIXED_REPLY = "(高兴)(收到邀请很开心)你好呀"


def valid_message(message_id: str = "msg-001") -> dict:
    return {
        "type": "client_query",
        "message_id": message_id,
        "payload": {
            "textModel_config": {
                "text": {"role": "user", "content": "你好"},
                "modelText": "mock-model",
            },
            "role": "Wendy",
            "imageModel_config": {
                "modelImage": "mock-image",
                "realTimeRendering": False,
            },
            "voiceCate": "ElderSister",
        },
    }


def fixed_response(message: str = FIXED_REPLY) -> Connect.ServerResponse:
    return Connect.ServerResponse(
        response=message,
        emotion="happy",
        index="3",
        metrics={"time_cost": 0.01, "tokens_used": len(message)},
        imageUrl="",
    )


class QueueWebSocket:
    """让 receive_text 与 receive_json 消费同一个客户端消息队列。"""

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []
        self.accepted = False
        self.client_state = WebSocketState.CONNECTED

    async def accept(self):
        self.accepted = True

    def _pop(self):
        if not self.incoming:
            self.client_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(code=1000)
        return self.incoming.pop(0)

    async def receive_text(self):
        item = self._pop()
        return item if isinstance(item, str) else json.dumps(item)

    async def receive_json(self):
        item = self._pop()
        return json.loads(item) if isinstance(item, str) else item

    async def send_json(self, message):
        self.sent.append(message)


async def run_socket(incoming, monkeypatch, response=None):
    websocket = QueueWebSocket(incoming)
    if response is not None:
        monkeypatch.setattr(Connect, "process_query", lambda _request: response)
    await Connect.websocket_chat(websocket)
    return websocket


def prepare_full_static_flow(monkeypatch, tmp_path: Path):
    backend_dir = tmp_path / "backend"
    assets_dir = tmp_path / "frontend" / "src" / "assets"
    pictures_dir = assets_dir / "pictures" / "Wendy"
    voice_dir = assets_dir / "voice" / "Wendy"
    backend_dir.mkdir()
    pictures_dir.mkdir(parents=True)
    voice_dir.mkdir(parents=True)
    records = assets_dir / "Records.txt"
    records.write_text("Wendy:\nRecent_Url:old-url\nindex:3\n", encoding="utf-8")
    for emotion, _description in Image.emo_image:
        (pictures_dir / f"Wendy_{emotion}.jpg").write_bytes(b"fixed-image")
    monkeypatch.chdir(backend_dir)
    monkeypatch.setattr(Integration, "get_llm_response", lambda *_args: FIXED_REPLY)

    def fixed_tts(role, _voice, _emotion, _text, index):
        path = voice_dir / f"{role}_{index}_Stream.mp3"
        path.write_bytes(b"fixed-audio")
        return str(path)

    monkeypatch.setattr(Integration, "Voice_Generation_through_http", fixed_tts)
    monkeypatch.setattr(Integration, "static_images", Image.static_images)
    monkeypatch.setattr(Connect, "Response_Collection", Integration.Response_Collection)
    return records, voice_dir


@pytest.mark.asyncio
async def test_tc_ws_01_valid_static_request_full_flow(monkeypatch, tmp_path):
    """TC-WS-01：合法请求的静态资源完整主流程。"""
    records, voice_dir = prepare_full_static_flow(monkeypatch, tmp_path)
    websocket = await run_socket(
        [valid_message(), {"message_id": "msg-001"}], monkeypatch
    )
    response = websocket.sent[0]
    assert response["type"] == "assistant_response"
    assert response["message_id"] == "msg-001"
    assert response["status"] == "success"
    assert response["payload"]["response"] == FIXED_REPLY
    assert response["payload"]["emotion"] == "happy"
    assert response["payload"]["index"] == "3"
    assert response["payload"]["metrics"]["time_cost"] >= 0
    assert response["payload"]["metrics"]["tokens_used"] == len(FIXED_REPLY)
    assert response["payload"]["imageUrl"] == ""
    assert (voice_dir / "Wendy_3_Stream.mp3").read_bytes() == b"fixed-audio"
    assert "index:4" in records.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_tc_ws_02_invalid_json_then_connection_survives(monkeypatch):
    """TC-WS-02：非法 JSON 返回解析错误且连接继续可用。"""
    websocket = await run_socket(
        ["{invalid-json", valid_message(), {"message_id": "msg-001"}],
        monkeypatch,
        fixed_response(),
    )
    assert websocket.sent[0]["type"] == "error"
    assert websocket.sent[0]["code"] == "JSON_PARSE_ERROR"
    assert websocket.sent[0]["message"] == "请求格式出错。"
    assert "detail" in websocket.sent[0]
    assert websocket.sent[1]["type"] == "assistant_response"


@pytest.mark.asyncio
async def test_tc_ws_04_non_client_query_rejected_without_side_effect(monkeypatch):
    """TC-WS-04：非 client_query 消息被拒绝且连接可复用。"""
    calls = []
    monkeypatch.setattr(
        Connect, "process_query", lambda request: calls.append(request) or fixed_response()
    )
    wrong = valid_message()
    wrong["type"] = "canceled_request"
    websocket = await run_socket(
        [wrong, valid_message(), {"message_id": "msg-001"}], monkeypatch
    )
    assert websocket.sent[0]["code"] == "INVALID_MSG_TYPE"
    assert websocket.sent[1]["type"] == "assistant_response"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tc_ws_05_missing_type_returns_server_error(monkeypatch):
    """TC-WS-05：缺少顶层 type 时进入 SERVER_ERROR。"""
    calls = []
    monkeypatch.setattr(Connect, "process_query", lambda request: calls.append(request))
    message = valid_message()
    del message["type"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["code"] for item in websocket.sent] == ["SERVER_ERROR"]
    assert calls == []


@pytest.mark.asyncio
async def test_tc_ws_06_missing_payload_returns_server_error(monkeypatch):
    """TC-WS-06：缺少 payload 时进入 SERVER_ERROR。"""
    calls = []
    monkeypatch.setattr(Connect, "process_query", lambda request: calls.append(request))
    message = valid_message()
    del message["payload"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["code"] for item in websocket.sent] == ["SERVER_ERROR"]
    assert calls == []


@pytest.mark.asyncio
async def test_tc_ws_07_missing_required_payload_field(monkeypatch):
    """TC-WS-07：payload 缺少 role 时返回 VALIDATION_ERROR。"""
    calls = []
    monkeypatch.setattr(Connect, "process_query", lambda request: calls.append(request))
    message = valid_message()
    del message["payload"]["role"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["code"] for item in websocket.sent] == ["VALIDATION_ERROR"]
    assert calls == []


@pytest.mark.asyncio
async def test_tc_ws_08_error_response_is_frontend_incompatible():
    """TC-WS-08：记录当前错误响应不符合前端 server-message 契约。"""
    websocket = QueueWebSocket()
    await Connect.send_error(websocket, "JSON_PARSE_ERROR", "fixed detail")
    error = websocket.sent[0]
    assert {"type", "code", "message", "detail"} <= error.keys()
    frontend_required = {"type", "message_id", "status", "payload"}
    assert not frontend_required <= error.keys()


@pytest.mark.asyncio
async def test_tc_cfg_01_missing_model_text_reports_processing_errors(monkeypatch):
    """TC-CFG-01：缺少 modelText，不调用 LLM，并观察双错误响应。"""
    external_calls = []
    monkeypatch.setattr(
        Connect, "Response_Collection", lambda *_args: external_calls.append(True)
    )
    message = valid_message()
    del message["payload"]["textModel_config"]["modelText"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["code"] for item in websocket.sent] == [
        "PROCESS_ERROR",
        "SERVER_ERROR",
    ]
    assert external_calls == []


@pytest.mark.asyncio
async def test_tc_cfg_02_missing_realtime_flag_reports_processing_errors(monkeypatch):
    """TC-CFG-02：缺少 realTimeRendering，不调用 LLM，并观察双错误响应。"""
    external_calls = []
    monkeypatch.setattr(
        Connect, "Response_Collection", lambda *_args: external_calls.append(True)
    )
    message = valid_message()
    del message["payload"]["imageModel_config"]["realTimeRendering"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["code"] for item in websocket.sent] == [
        "PROCESS_ERROR",
        "SERVER_ERROR",
    ]
    assert external_calls == []


@pytest.mark.asyncio
async def test_tc_cfg_06_unknown_model_forwarded_then_rejected(monkeypatch):
    """TC-CFG-06：未知模型原样透传，服务拒绝后进入错误路径。"""
    received = []

    def reject(model, *_args):
        received.append(model)
        raise RuntimeError("fixed provider rejection")

    monkeypatch.setattr(Connect, "Response_Collection", reject)
    message = valid_message()
    message["payload"]["textModel_config"]["modelText"] = "not-supported-model"
    websocket = await run_socket([message], monkeypatch)
    assert received == ["not-supported-model"]
    assert [item["code"] for item in websocket.sent] == [
        "PROCESS_ERROR",
        "SERVER_ERROR",
    ]


@pytest.mark.asyncio
async def test_tc_ex_03_disconnect_isolated_from_other_connection(monkeypatch):
    """TC-EX-03：一个客户端断开不影响另一独立连接。"""
    disconnected = await run_socket([], monkeypatch)
    healthy = await run_socket(
        [valid_message("healthy"), {"message_id": "healthy"}],
        monkeypatch,
        fixed_response(),
    )
    assert disconnected.accepted and disconnected.sent == []
    assert healthy.sent[0]["message_id"] == "healthy"


@pytest.mark.asyncio
async def test_tc_ack_01_matching_ack_allows_next_request(monkeypatch):
    """TC-ACK-01：匹配 ACK 后继续处理下一请求。"""
    websocket = await run_socket(
        [
            valid_message("m1"),
            {"message_id": "m1"},
            valid_message("m2"),
            {"message_id": "m2"},
        ],
        monkeypatch,
        fixed_response(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_tc_ack_02_timeout_allows_next_request(monkeypatch):
    """TC-ACK-02：ACK 超时后连接仍处理下一请求。"""
    real_wait_for = Connect.asyncio.wait_for
    calls = 0

    async def timeout_once(awaitable, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            awaitable.close()
            raise Connect.asyncio.TimeoutError
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(Connect.asyncio, "wait_for", timeout_once)
    websocket = await run_socket(
        [valid_message("m1"), valid_message("m2"), {"message_id": "m2"}],
        monkeypatch,
        fixed_response(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_tc_ack_03_next_query_is_consumed_as_ack(monkeypatch):
    """TC-ACK-03：未 ACK 时下一业务请求被当前实现误当成 ACK。"""
    websocket = await run_socket(
        [valid_message("m1"), valid_message("m2")],
        monkeypatch,
        fixed_response(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1"]
