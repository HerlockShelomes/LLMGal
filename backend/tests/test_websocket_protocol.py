from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

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


class ScriptedWebSocket:
    def __init__(self, text_messages: list[str] | None = None, json_messages: list[dict] | None = None):
        self.text_messages = list(text_messages or [])
        self.json_messages = list(json_messages or [])
        self.sent: list[dict] = []
        self.client_state = WebSocketState.CONNECTED
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if not self.text_messages:
            raise WebSocketDisconnect(code=1000)
        return self.text_messages.pop(0)

    async def receive_json(self):
        if not self.json_messages:
            raise WebSocketDisconnect(code=1000)
        return self.json_messages.pop(0)

    async def send_json(self, message):
        self.sent.append(message)


@pytest.mark.asyncio
async def test_error_response_uses_frontend_server_message_envelope():
    websocket = ScriptedWebSocket()

    await Connect.send_error(websocket, "JSON_PARSE_ERROR", "bad json", message_id="msg-001")

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
async def test_process_failure_returns_one_error_and_does_not_use_unassigned_response(monkeypatch):
    websocket = ScriptedWebSocket([json.dumps(valid_message())])

    def fail_process(_request):
        raise RuntimeError("mock processing failure")

    monkeypatch.setattr(Connect, "process_query", fail_process)

    await Connect.websocket_chat(websocket)

    assert [message["payload"]["code"] for message in websocket.sent] == ["PROCESS_ERROR"]


@pytest.mark.asyncio
async def test_missing_nested_model_field_is_validation_error(monkeypatch):
    message = valid_message()
    del message["payload"]["textModel_config"]["modelText"]
    websocket = ScriptedWebSocket([json.dumps(message)])
    process_calls = 0

    def count_process(_request):
        nonlocal process_calls
        process_calls += 1
        raise AssertionError("invalid input must not reach process_query")

    monkeypatch.setattr(Connect, "process_query", count_process)

    await Connect.websocket_chat(websocket)

    assert process_calls == 0
    assert [message["payload"]["code"] for message in websocket.sent] == ["VALIDATION_ERROR"]
