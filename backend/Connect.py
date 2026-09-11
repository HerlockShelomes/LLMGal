"""FastAPI entry point and WebSocket protocol for the LLMGal backend.

The expensive LLM, image, and speech orchestration remains in ``Integration``.
This module is intentionally limited to request validation, response envelopes,
and per-connection ACK handling so it can be tested without external services.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import FastAPI, WebSocket
from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocketDisconnect

from Integration import Response_Collection


ACK_TIMEOUT_SECONDS = 30.0

app = FastAPI(title="LLM Galgame Chat Backend")


class TextModelConfig(BaseModel):
    """Text-generation settings supplied by the frontend."""

    text: dict[str, Any]
    modelText: str


class ImageModelConfig(BaseModel):
    """Image-generation settings supplied by the frontend."""

    modelImage: str
    realTimeRendering: bool


class ClientRequest(BaseModel):
    """Validated business payload of a ``client_query`` message."""

    textModel_config: TextModelConfig
    role: str
    imageModel_config: ImageModelConfig
    voiceCate: str


class ServerResponse(BaseModel):
    """Business payload returned to the frontend."""

    response: str
    emotion: str
    index: str
    metrics: dict[str, Any]
    imageUrl: str


def process_query(request: ClientRequest) -> ServerResponse:
    """Run the existing orchestration layer for one validated request."""

    start_time = time.time()
    response, index, emotion, image_url = Response_Collection(
        request.textModel_config.modelText,
        request.imageModel_config.modelImage,
        request.role,
        request.voiceCate,
        request.imageModel_config.realTimeRendering,
        request.textModel_config.text,
    )
    return ServerResponse(
        response=response,
        emotion=emotion,
        index=index,
        metrics={
            "time_cost": time.time() - start_time,
            "tokens_used": len(response),
        },
        imageUrl=image_url,
    )


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "alive"}


def _error_message(code: str) -> str:
    if code == "PROCESS_ERROR":
        return "请求处理失败。"
    if code == "SERVER_ERROR":
        return "内部服务器出错。"
    return "请求格式出错。"


async def send_error(
    websocket: WebSocket,
    code: str,
    detail: str | None = None,
    *,
    message_id: str = "",
) -> None:
    """Send an error using the same envelope consumed by the frontend."""

    error_message = {
        "type": "error",
        "message_id": message_id,
        "status": "failure",
        "payload": {
            "code": code,
            "message": _error_message(code),
            "detail": detail or "",
        },
    }
    try:
        await websocket.send_json(error_message)
    except (WebSocketDisconnect, RuntimeError):
        logging.warning("连接已关闭，错误消息发送失败。")


def _message_id(message: Any) -> str:
    if isinstance(message, dict) and isinstance(message.get("message_id"), str):
        return message["message_id"]
    return ""


def _validation_detail(message: Any) -> str | None:
    """Return a validation error description, or ``None`` when valid."""

    if not isinstance(message, dict):
        return "WebSocket 消息必须是 JSON 对象"
    if "type" not in message:
        return "缺少顶层字段 type"
    if not isinstance(message.get("message_id"), str) or not message["message_id"]:
        return "缺少或无效的顶层字段 message_id"
    if "payload" not in message:
        return "缺少顶层字段 payload"
    if not isinstance(message["payload"], dict):
        return "顶层字段 payload 必须是 JSON 对象"
    return None


async def websocket_chat(websocket: WebSocket) -> None:
    """Serve one client while keeping protocol state local to its connection."""

    await websocket.accept()
    buffered_message: dict[str, Any] | None = None

    while True:
        message: Any = None
        try:
            if buffered_message is None:
                raw_data = await websocket.receive_text()
                try:
                    message = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    await send_error(websocket, "JSON_PARSE_ERROR", str(exc))
                    continue
            else:
                message = buffered_message
                buffered_message = None

            message_id = _message_id(message)
            detail = _validation_detail(message)
            if detail is not None:
                await send_error(
                    websocket,
                    "VALIDATION_ERROR",
                    detail,
                    message_id=message_id,
                )
                continue

            if message["type"] != "client_query":
                await send_error(
                    websocket,
                    "INVALID_MSG_TYPE",
                    f"Invalid Message Type: {message['type']}",
                    message_id=message_id,
                )
                continue

            try:
                client_request = ClientRequest(**message["payload"])
            except (ValidationError, TypeError, ValueError) as exc:
                await send_error(
                    websocket,
                    "VALIDATION_ERROR",
                    str(exc),
                    message_id=message_id,
                )
                continue

            try:
                response = process_query(client_request)
            except Exception as exc:  # orchestration failures become protocol errors
                logging.exception("处理查询失败")
                await send_error(
                    websocket,
                    "PROCESS_ERROR",
                    str(exc),
                    message_id=message_id,
                )
                continue

            response_message = {
                "type": "assistant_response",
                "message_id": message_id,
                "status": "success",
                "payload": {
                    "response": response.response,
                    "emotion": response.emotion,
                    "index": response.index,
                    "metrics": response.metrics,
                    "imageUrl": response.imageUrl,
                },
            }
            await websocket.send_json(response_message)

            try:
                ack_raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=ACK_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logging.info("[ACK 超时] 消息 ID: %s", message_id)
                continue

            try:
                ack_or_message = json.loads(ack_raw)
            except json.JSONDecodeError as exc:
                await send_error(websocket, "JSON_PARSE_ERROR", str(exc))
                continue

            # A new query can arrive before the ACK. Preserve it for the next
            # loop iteration instead of consuming it as a mismatched ACK.
            if (
                isinstance(ack_or_message, dict)
                and ack_or_message.get("type") == "client_query"
            ):
                buffered_message = ack_or_message
            elif (
                isinstance(ack_or_message, dict)
                and ack_or_message.get("message_id") == message_id
            ):
                logging.info("[ACK 已确认] 消息 ID: %s", message_id)
            else:
                logging.warning("[ACK 不匹配] 消息 ID: %s", message_id)

        except WebSocketDisconnect:
            logging.info("客户端断开连接")
            break
        except Exception as exc:
            logging.exception("WebSocket 处理异常")
            await send_error(
                websocket,
                "SERVER_ERROR",
                str(exc),
                message_id=_message_id(message),
            )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
