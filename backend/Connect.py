import asyncio
import websockets
import json
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocketDisconnect, WebSocketState

from Integration import Response_Collection
import logging
from websockets.exceptions import ConnectionClosedError
from Voice import parse_response

import config
import Text

# 连接管理器
class WebSocketManager:
    def __init__(self):
        self.active_connections = {}

    async def connect_inner(self, url, headers):
        """创建完全独立的内部连接"""
        inner_ws = await websockets.connect(url, extra_headers=headers, ping_interval=None)

        conn_id = id(inner_ws)
        self.active_connections[conn_id] = inner_ws
        return conn_id

    async def close_inner(self, conn_id):
        """安全关闭内层连接"""
        if conn_id in self.active_connections:
            await self.active_connections[conn_id].close()
            del self.active_connections[conn_id]

ws_manager = WebSocketManager()

async def inner_websocket_operation(api_url, full_client, file_to_save):


    """隔离的内层WebSocket调用"""
    try:
        conn_id = await ws_manager.connect_inner(api_url,
        {"Authorization": f"Bearer; {config.TTS_VOLC_TOKEN}"}
        )
        inner_ws = ws_manager.active_connections[conn_id]

        await inner_ws.send(full_client)

        # 安全退出条件

        while True:
            try:
                res = await asyncio.wait_for(inner_ws.recv(), timeout=30.0)
            except asyncio.TimeoutError:
                break

            done = parse_response(res, file_to_save)
            if done:
                file_to_save.close()
                break

    except websockets.ConnectionClosed as e:
        logging.warning(f'Inner WS closed: {e.code}')
    finally:
        # 资源清理
        if not file_to_save.closed:
            file_to_save.close()
        # 安全关闭内层链接
        if 'conn_id' in locals():
            await ws_manager.close_inner(conn_id)
            print('Inner Connection Closed')

# OK, Let's start all this all over again, but for one last time.
# We are going to build a connection with Vue Frontend.
# Start the construction with the format of the message.
# The link will be established with FastAPI.
# Let's Finish this. 2025.7.9-20:33

# The format of the Received message.
# {
#   "type": "client_query",         // 固定消息类型标识
#   "message_id": "session_1234",  // 客户端生成的唯一消息ID, 注意了解一下生成机理。
#   "timestamp": "2023-08-20T15:30:00Z", // 不是那么必要，但可以保留，作为消息传输的时间戳。
#   "payload": {
#     "textModel_config":{
#       "text": "请用莎士比亚的风格写首诗",  // 用户输入文本
#       "modelText": "deepseek-ai/DeepSeek-V3"      // 选择的模型名称
#     },
#     "role": "Wendy",                        //角色选择
#     "imageModel_config": {
#       "modelImage": "high_aes_ip_v20",      //图片模型选择（文生图亦或图生图）
#       "realTimeRendering": true       // 是否选择实时渲染
#     },
#     "voiceCate": "GirlFriend"    //选择模型使用的音色
#   }
# }
#
# The message format sending back to the frontend.
#
# {
#   "type": "assistant_response",   //消息类型标识符，用于确认消息格式。
#   "message_id": "session_1234",   // 必须与请求ID对应，前端获取之后也需要正常返回
#   "status": "success",            // success/partial/failure  状态表达需要之后规范。
#   "payload": {
#     "response": "汝之眼眸如星河璀璨...",  // 模型生成的文本
#     "emotion": "neutral",          // 情绪标签，具体可生成的情绪标签可参考Integration.py
#     "index": "0",    // 资源标识符，在0-9之间循环，代表可使用实时生成的图片资源最大数量为10.
#     "metrics": {
#       "time_cost": 2.34,          // 单位：秒
#       "tokens_used": 789
#     },
#     imageUrl: "https://xxxx.com" // 更新的图片url，现在传入可能意义不大，因为提取、写入、更新这几步全是在后端完成。但保留这一项，
#                                  // 后续如果用户希望进一步节省内存，可以直接调用url。url失效时图片会消失，就调用文生图模型重新生成。
#   }
# }
#
# Error Message Format:
# {
#   "type": "error",                            // 消息类型标识符，这一个类型消息指向传输错误；
#   "message_id": "session_1234",               // 消息ID，从前端传过来的ID和从后端反馈的ID必须要对应一样。
#   "code": "AUTH_403",                         // 错误代码，指向此次错误的类型。
#   "message": "无效的音色ID配置",                 // 错误信息，具体描述错误代码的含义
#   "detail": "voice_id=vivi-3 不存在于配置库"     // 错误详情，指出此次错误的具体原因，便于调试错误。
# }
# 好像还没写，后续看能不能完善一下。

app = FastAPI(title="LLM Galgame Chat Backend")

# 跨域：默认放行方便本地开发；生产请在 .env 里把 CORS_ALLOW_ORIGINS 收敛成前端域名。
_origins = [item.strip() for item in config.CORS_ALLOW_ORIGINS.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup_check():
    """启动时自检配置，避免"跑起来了才发现没填密钥"。"""
    print("[LLMGal] 当前配置：")
    print(config.describe())
    if not config.WS_AUTH_TOKEN:
        print("[LLMGal] 警告：未设置 WS_AUTH_TOKEN，WebSocket 处于无鉴权状态，"
              "任何能访问该端口的人都能消耗你的 API 额度。请在 .env 中配置。")

# 等到基础功能实现之后需要完善每一个消息传输的参数验证逻辑。

class ClientRequest(BaseModel):
    textModel_config: dict
    # "textModel_config":{
    #   "text": "请用莎士比亚的风格写首诗",  // 用户输入文本
    #   "modelText": "deepseek-ai/DeepSeek-V3"      // 选择的模型名称
    # },
    role: str
    # "role": "Wendy",                        //角色选择
    imageModel_config: dict
    # "imageModel_config": {
    #   "modelImage": "high_aes_ip_v20",      //图片模型选择（文生图亦或图生图）
    #   "realTimeRendering": true       // 是否选择实时渲染
    # },
    voiceCate: str
    # "voiceCate": "GirlFriend"    //选择模型使用的音色
    # 多轮上下文：历史消息列表 [{role, content}, ...]，按时间正序，不含当前这条。
    history: list = []
    # 会话标识，便于日志追踪（不参与生成）。
    sessionId: str = ""

    # BaseModel是已经包含基本的type, message_id, timestamp, status信息了吗？
    # 为什么我们构建的时候好像只需要考虑payload里的信息呢？


class ServerResponse(BaseModel):
    response: str
    # "response": "汝之眼眸如星河璀璨...",  // 模型生成的文本
    emotion: str
    # "emotion": "neutral",          // 情绪标签，具体可生成的情绪标签可参考Integration.py
    index: str
    # "index": "0",    // 资源标识符，在0-9之间循环，代表可使用实时生成的图片资源最大数量为10.
    metrics: dict
    # "metrics": {
    #   "time_cost": 2.34,          // 单位：秒
    #   "tokens_used": 789
    # },
    imageUrl: str
    # imageUrl: "https://xxxx.com" // 更新的图片url，现在传入可能意义不大，因为提取、写入、更新这几步，全是在后端完成。但保留这一项，
    #                              // 后续如果用户希望进一步节省内存，可以直接调用url。url失效时图片会消失，就调用文生图模型重新生成。
    # success / partial：语音或图片任一失败时降级为 partial（缺陷 009）
    status: str = "success"

def process_query(request: ClientRequest) -> ServerResponse:
    """
    获取从前端传输的数据，
    调用已有的大语言模型获得回复
    """
    default_metrics = { "time_cost": 0, "tokens_used": 0 }
    respond = ServerResponse(
        response = "",
        emotion = "",
        index = "8",
        metrics = default_metrics,
        imageUrl = ""
    )

    try:
        startTime = time.time()

        # 第 7 个参数把多轮历史交给编排层，否则模型永远只看得到当前这一句。
        response, indexStr, imageEmo, recentUrl, proc_status = Response_Collection(
                                                                      request.textModel_config["modelText"],
                                                                      request.imageModel_config["modelImage"],
                                                                      request.role,
                                                                      request.voiceCate,
                                                                      request.imageModel_config["realTimeRendering"],
                                                                      request.textModel_config["text"],
                                                                      request.history)

        respond.response = response
        respond.emotion = imageEmo
        respond.index = indexStr
        respond.imageUrl = recentUrl
        respond.status = proc_status or "success"
        stopTime = time.time()
        # 优先用模型返回的真实 token 用量；拿不到时退回按中文字符数粗估，
        # 并在字段上标注 est_ 前缀，避免把估算值当成真实用量。
        usage = getattr(Text, "LAST_USAGE", None)
        if usage and usage.get("total_tokens"):
            respond.metrics["tokens_used"] = usage["total_tokens"]
            respond.metrics["tokens_used_est"] = False
        else:
            respond.metrics["tokens_used"] = len(response)
            respond.metrics["tokens_used_est"] = True
        respond.metrics["time_cost"] = stopTime - startTime
        # "metrics": {
        #   "time_cost": 2.34,          // 单位：秒
        #   "tokens_used": 789
        # },
        return respond
    except Exception as e:
        logging.error(f"处理请求异常：{str(e)}")
        raise

def _validate_payload(payload) -> str:
    """校验 payload 的内容合法性，返回失败原因（通过时返回空串）。

    与 Pydantic 的类型校验互补：这里管"字段在但内容不对"的情况，
    例如 text 不是消息对象、history 不是数组。用独立的 invalid_message
    类型回给前端，区别于结构性的 VALIDATION_ERROR。
    """
    if not isinstance(payload, dict):
        return "payload 必须是对象"

    text_model = payload.get('textModel_config')
    if not isinstance(text_model, dict):
        return "textModel_config 缺失或格式错误"
    if 'text' not in text_model:
        return "textModel_config.text 缺失"

    image_model = payload.get('imageModel_config')
    if not isinstance(image_model, dict):
        return "imageModel_config 缺失或格式错误"

    history = payload.get('history')
    if history is not None:
        if not isinstance(history, list):
            return "history 必须是消息数组"
        for item in history:
            if not isinstance(item, dict) or 'content' not in item:
                return "history 中每条消息需包含 role 与 content"
    return ""


@app.get("/")
def health_check():
    return {"status": "alive"}


@app.get("/health/config")
def config_check():
    """启动自检：告诉前端/运维当前用的是哪套模型、还缺哪些密钥（不返回密钥本身）。"""
    return {
        "status": "alive",
        "text_provider": config.TEXT_PROVIDER,
        "text_model": config.TEXT_MODEL,
        "tts_provider": config.TTS_PROVIDER,
        "image_provider": config.IMAGE_PROVIDER,
        "auth_enabled": bool(config.WS_AUTH_TOKEN),
        "missing": config.missing_credentials(),
    }

@app.get("/voices")
def list_voices():
    """音色目录 + 角色->音色映射，供前端设置面板展示与微调。"""
    return {
        "provider": config.TTS_PROVIDER,
        "catalog": [
            {"id": voice_id, "name": info[0], "gender": info[1], "desc": info[2]}
            for voice_id, info in config.QWEN_VOICE_CATALOG.items()
        ],
        "role_voices": config.ROLE_VOICES,
    }


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    # 缺陷 B02：可选的接入鉴权。配置了 WS_AUTH_TOKEN 之后，连接必须带同名 token，
    # 否则任何人都能连上来消耗你的免费额度。未配置时保持开发模式（启动会告警）。
    if config.WS_AUTH_TOKEN:
        query_params = getattr(websocket, "query_params", None)
        supplied = query_params.get("token") if query_params else None
        if not supplied:
            headers = getattr(websocket, "headers", None)
            if headers:
                supplied = headers.get("x-auth-token")
        if supplied != config.WS_AUTH_TOKEN:
            await send_error(websocket, "AUTH_403", "鉴权失败：token 无效或缺失")
            try:
                await websocket.close()
            except Exception:
                pass
            return

    try:
        # 待确认的响应ID。发送响应后记录，下一条消息若是它的回执才消费，
        # 不是回执就按普通业务请求处理，避免把用户请求当成 ACK 吞掉。
        pending_ack_id = None
        while True:
            try:
                # 接收并解析消息
                raw_data = await websocket.receive_text()
                try:
                    message = json.loads(raw_data)
                except json.JSONDecodeError as e:
                    await send_error(websocket, "JSON_PARSE_ERROR", str(e))
                    continue

                # 先判定是否为上一条响应的确认回执。
                # 仅当 message_id 与待确认ID一致、且不是新的业务请求时才消费掉；
                # 否则继续按业务请求处理，避免下一条提问被误当成 ACK 吞掉。
                if (
                    pending_ack_id is not None
                    and message.get('message_id') == pending_ack_id
                    and message.get('type') != 'client_query'
                ):
                    print(f"[确认送达] 消息ID: {pending_ack_id}")
                    pending_ack_id = None
                    continue

                # 基础验证（缺 type 会抛 KeyError，交由外层兜底为 SERVER_ERROR）
                msg_type = message['type']
                # 心跳与取消属于控制帧，不能当成非法业务消息回错误，
                # 否则前端每一次心跳都会弹一条错误提示。
                if msg_type in ('heartbeat', 'ping'):
                    await websocket.send_json({
                        "type": "pong",
                        "message_id": message.get('message_id', ''),
                        "status": "success",
                        "payload": {},
                    })
                    continue
                if msg_type == 'canceled_request':
                    # 用户中止：清掉待确认回执即可，生成中的请求结果到达后由前端自行忽略。
                    print(f"[取消请求] 消息ID: {message.get('message_id', '')}")
                    pending_ack_id = None
                    continue

                if msg_type != 'client_query':
                    await send_error(
                        websocket,
                        "INVALID_MSG_TYPE",
                        f"Invalid Message Type: {message['type']}",
                        message_id=message.get('message_id', ''),
                    )
                    continue

                # 语义校验：Pydantic 只校验类型，这里再校验内容是否可用。
                # 与 VALIDATION_ERROR 区分开，用独立的 invalid_message 类型告知前端。
                payload = message['payload']
                reason = _validate_payload(payload)
                if reason:
                    await websocket.send_json({
                        "type": "invalid_message",
                        "message_id": message.get('message_id', ''),
                        "status": "error",
                        "reason": reason,
                        "payload": {"reason": reason},
                    })
                    continue

                # 执行处理逻辑
                try:
                    client_request = ClientRequest(**message['payload'])
                except ValueError as e:
                    await send_error(
                        websocket,
                        "VALIDATION_ERROR",
                        str(e),
                        message_id=message.get('message_id', ''),
                    )
                    continue
                try:
                    # 缺陷 B03：Response_Collection 内部是同步的网络调用（LLM/TTS/图像），
                    # 直接在事件循环里跑会把整个服务阻塞住，并发一超 1 就假死。
                    # 这里卸载到线程池，事件循环继续处理心跳与取消。
                    resp = await asyncio.to_thread(process_query, client_request)
                except Exception as e:
                    logging.error(f'处理查询失败: {str(e)}')
                    await send_error(
                        websocket,
                        "PROCESS_ERROR",
                        f"处理失败: {str(e)}",
                        message_id=message.get('message_id', ''),
                    )
                    # 处理失败时必须跳出本轮循环，否则 resp 未绑定，
                    # 下面构造响应消息会再抛 NameError，导致一次失败连发两条错误响应。
                    continue

                # 构造返回消息（状态如实透传：语音/图片失败时为 partial）
                respond_msg = {
                    "type": "assistant_response",
                    "message_id": message['message_id'],
                    "status": getattr(resp, "status", "success") or "success",
                    "payload": {
                        "response": resp.response,
                        "emotion": resp.emotion,
                        "index": resp.index,
                        "metrics":{
                            "time_cost": resp.metrics['time_cost'],
                            "tokens_used": resp.metrics['tokens_used'],
                        },
                        "imageUrl": resp.imageUrl
                    },
                }
                try:
                    await websocket.send_json(respond_msg)
                    if websocket.client_state == WebSocketState.CONNECTED:
                        print(f"[发送成功]，消息ID: {message['message_id']}，类型为: {respond_msg['type']}")
                    else:
                        print("消息已发送，但未经确认")
                        continue
                except Exception as e:
                    print(f'消息发送出错: {str(e)}')
                # 只登记待确认的响应ID，不再阻塞式等待下一条消息。
                # 原先在此处直接 receive_json() 会把用户紧接着发来的下一条业务
                # 请求误当成 ACK 消费掉且不重放，导致该请求被永久丢弃。
                pending_ack_id = respond_msg['message_id']

            except WebSocketDisconnect as e:
                print('客户端断开连接', e)
                break
    except WebSocketDisconnect as e:
        print("连接断开", e)
    except Exception as e:
        logging.exception("WebSocket Fetal Error.")
        await send_error(websocket, "SERVER_ERROR", str(e))
    # finally:
    #     # 关闭连接，清理缓存
    #     await websocket.close()

async def send_error(websocket: WebSocket, code: str, detail: str = None, message_id: str = ""):
    """回传错误消息。

    必须携带 message_id 与 payload：前端的 isServerMessage 会校验
    type / message_id / payload 三项，缺任一项都会被判为非法消息并丢弃，
    错误提示根本无法到达用户。顶层同时保留 code/message/detail 以兼容既有消费者。
    """
    text = "内部服务器出错。" if code == "SERVER_ERROR" else "请求格式出错。"
    error_msg = {
        "type": "error",
        "message_id": message_id,
        "status": "error",
        "code": code,
        "message": text,
        # 错误类型后续最好整理一下，暂时考虑的只有这两种。
        "payload": {
            "code": code,
            "message": text,
            "detail": detail or "",
        },
    }

    #   "type": "error",                            // 消息类型标识符，这一个类型消息指向传输错误；
    #   "message_id": "session_1234",               // 消息ID，从前端传过来的ID和从后端反馈的ID必须要对应一样。
    #   "code": "AUTH_403",                         // 错误代码，指向此次错误的类型。
    #   "message": "无效的音色ID配置",                 // 错误信息，具体描述错误代码的含义
    #   "detail": "voice_id=vivi-3 不存在于配置库"     // 错误详情，指出此次错误的具体原因，便于调试错误。

    if detail:
        error_msg["detail"] = detail
    try:
        await websocket.send_json(error_msg)
    except ConnectionClosedError:
        logging.warning("连接已关闭，消息发送失败。")

if __name__ == "__main__":
    import uvicorn
    # 默认只监听本机（缺陷 B02）：原先绑定 0.0.0.0 且无鉴权，等于把 API 额度暴露在网络上。
    # 需要局域网/外网访问时，在 .env 里显式设置 HOST，并务必同时配置 WS_AUTH_TOKEN。
    # 开启 reload 时 Uvicorn 必须接收可重新导入的应用字符串；直接传 app
    # 对象会在新版 Uvicorn 中拒绝启动。默认关闭 watcher，避免受限目录、容器
    # 或部分 Windows 环境中因文件监视器而启动失败；开发时可设 DEV_RELOAD=1。
    uvicorn.run(
        "Connect:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEV_RELOAD,
    )
