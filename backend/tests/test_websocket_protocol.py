from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

import Connect


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


def fake_result(text: str = "(高兴)(收到邀请)你好") -> Connect.ServerResponse:
    return Connect.ServerResponse(
        response=text,
        emotion="happy",
        index="3",
        metrics={"time_cost": 0.01, "tokens_used": len(text)},
        imageUrl="",
    )


class ScriptedWebSocket:
    def __init__(self, messages: list[str] | None = None):
        self.messages = list(messages or [])
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if not self.messages:
            raise WebSocketDisconnect(code=1000)
        return self.messages.pop(0)

    async def send_json(self, message):
        self.sent.append(message)


async def run_socket(messages: list[dict | str], monkeypatch, result=None):
    encoded = [item if isinstance(item, str) else json.dumps(item) for item in messages]
    websocket = ScriptedWebSocket(encoded)
    if result is not None:
        monkeypatch.setattr(Connect, "process_query", lambda _request: result)
    await Connect.websocket_chat(websocket)
    return websocket


@pytest.mark.asyncio
async def test_ws_01_valid_static_request_returns_success_and_updates_index(monkeypatch):
    websocket = await run_socket(
        [valid_message(), {"message_id": "msg-001"}], monkeypatch, fake_result()
    )
    assert websocket.accepted is True
    assert websocket.sent == [
        {
            "type": "assistant_response",
            "message_id": "msg-001",
            "status": "success",
            "payload": {
                "response": "(高兴)(收到邀请)你好",
                "emotion": "happy",
                "index": "3",
                "metrics": {"time_cost": 0.01, "tokens_used": 12},
                "imageUrl": "",
            },
        }
    ]


@pytest.mark.asyncio
async def test_ws_02_invalid_json_returns_parse_error_and_connection_survives(monkeypatch):
    websocket = await run_socket(
        ["{invalid-json", valid_message(), {"message_id": "msg-001"}],
        monkeypatch,
        fake_result(),
    )
    assert [item["type"] for item in websocket.sent] == ["error", "assistant_response"]
    assert websocket.sent[0]["payload"]["code"] == "JSON_PARSE_ERROR"


@pytest.mark.asyncio
async def test_ws_04_non_query_type_is_rejected_without_side_effects(monkeypatch):
    calls = 0

    def process(_request):
        nonlocal calls
        calls += 1
        return fake_result()

    monkeypatch.setattr(Connect, "process_query", process)
    wrong = valid_message()
    wrong["type"] = "canceled_request"
    websocket = await run_socket([wrong], monkeypatch)
    assert calls == 0
    assert websocket.sent[0]["payload"]["code"] == "INVALID_MSG_TYPE"


@pytest.mark.asyncio
async def test_ws_05_missing_type_returns_single_validation_error(monkeypatch):
    message = valid_message()
    del message["type"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["payload"]["code"] for item in websocket.sent] == ["VALIDATION_ERROR"]


@pytest.mark.asyncio
async def test_ws_06_missing_payload_returns_single_validation_error(monkeypatch):
    message = valid_message()
    del message["payload"]
    websocket = await run_socket([message], monkeypatch)
    assert [item["payload"]["code"] for item in websocket.sent] == ["VALIDATION_ERROR"]


@pytest.mark.asyncio
async def test_ws_07_missing_required_payload_field_returns_validation_error(monkeypatch):
    message = valid_message()
    del message["payload"]["role"]
    websocket = await run_socket([message], monkeypatch)
    assert websocket.sent[0]["payload"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_ws_08_error_response_matches_frontend_contract():
    websocket = ScriptedWebSocket()
    await Connect.send_error(
        websocket, "JSON_PARSE_ERROR", "bad json", message_id="msg-001"
    )
    assert websocket.sent == [
        {
            "type": "error",
            "message_id": "msg-001",
            "status": "failure",
            "payload": {
                "code": "JSON_PARSE_ERROR",
                "message": "请求格式出错。",
                "detail": "bad json",
            },
        }
    ]


@pytest.mark.asyncio
async def test_cfg_01_missing_model_text_returns_validation_error_without_llm_call(monkeypatch):
    message = valid_message()
    del message["payload"]["textModel_config"]["modelText"]
    process_calls = 0

    def process(_request):
        nonlocal process_calls
        process_calls += 1
        return fake_result()

    monkeypatch.setattr(Connect, "process_query", process)
    websocket = await run_socket([message], monkeypatch)
    assert process_calls == 0
    assert websocket.sent[0]["payload"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_cfg_02_missing_realtime_flag_returns_validation_error_without_llm_call(monkeypatch):
    message = valid_message()
    del message["payload"]["imageModel_config"]["realTimeRendering"]
    process_calls = 0

    def process(_request):
        nonlocal process_calls
        process_calls += 1
        return fake_result()

    monkeypatch.setattr(Connect, "process_query", process)
    websocket = await run_socket([message], monkeypatch)
    assert process_calls == 0
    assert websocket.sent[0]["payload"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_cfg_06_unknown_model_is_forwarded_and_failure_is_reported(monkeypatch):
    message = valid_message()
    message["payload"]["textModel_config"]["modelText"] = "not-supported-model"
    received_models: list[str] = []

    def fail(model, *_args):
        received_models.append(model)
        raise RuntimeError("provider rejected model")

    monkeypatch.setattr(Connect, "Response_Collection", fail)
    websocket = await run_socket([message], monkeypatch)
    assert received_models == ["not-supported-model"]
    assert [item["payload"]["code"] for item in websocket.sent] == ["PROCESS_ERROR"]


@pytest.mark.asyncio
async def test_ex_03_client_disconnect_does_not_affect_other_connections(monkeypatch):
    disconnected = ScriptedWebSocket()
    await Connect.websocket_chat(disconnected)
    healthy = await run_socket(
        [valid_message("msg-healthy"), {"message_id": "msg-healthy"}],
        monkeypatch,
        fake_result(),
    )
    assert disconnected.accepted and disconnected.sent == []
    assert healthy.sent[0]["message_id"] == "msg-healthy"


@pytest.mark.asyncio
async def test_ack_01_matching_ack_allows_next_request(monkeypatch):
    websocket = await run_socket(
        [
            valid_message("m1"),
            {"message_id": "m1"},
            valid_message("m2"),
            {"message_id": "m2"},
        ],
        monkeypatch,
        fake_result(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_ack_02_ack_timeout_allows_next_request(monkeypatch):
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
        fake_result(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_ack_03_next_query_is_not_consumed_as_ack(monkeypatch):
    websocket = await run_socket(
        [valid_message("m1"), valid_message("m2"), {"message_id": "m2"}],
        monkeypatch,
        fake_result(),
    )
    assert [item["message_id"] for item in websocket.sent] == ["m1", "m2"]
