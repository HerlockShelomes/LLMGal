import asyncio
import websockets
import json
from fastapi import FastAPI, WebSocket
from pydantic import BaseModel
import time
from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocketDisconnect, WebSocketState

from Integration import Response_Collection
import logging
from websockets.exceptions import ConnectionClosedError
from Voice import parse_response

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
        {"Authorization": "Bearer; _SRNKZhKXevBrx72wklF-D8NX7LGigGs"}
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

app = FastAPI(title  = "LLM Galgame Chat Backend")

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


        response, indexStr, imageEmo, recentUrl = Response_Collection(request.textModel_config["modelText"],
                                                                      request.imageModel_config["modelImage"],
                                                                      request.role,
                                                                      request.voiceCate,
                                                                      request.imageModel_config["realTimeRendering"],
                                                                      request.textModel_config["text"])

        respond.response = response
        respond.emotion = imageEmo
        respond.index = indexStr
        respond.imageUrl = recentUrl
        stopTime = time.time()
        # 这一段metrics尚未增入……后续确定一下
        respond.metrics["tokens_used"] = len(response)
        respond.metrics["time_cost"] = stopTime - startTime
        # "metrics": {
        #   "time_cost": 2.34,          // 单位：秒
        #   "tokens_used": 789
        # },
        return respond
    except Exception as e:
        logging.error(f"处理请求异常：{str(e)}")
        raise

@app.get("/")
def health_check():
    return {"status": "alive"}

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                # 接收并解析消息
                raw_data = await websocket.receive_text()
                try:
                    message = json.loads(raw_data)
                except json.JSONDecodeError as e:
                    await send_error(websocket, "JSON_PARSE_ERROR", str(e))
                    continue

                # 基础验证
                if message['type'] != 'client_query':
                    await send_error(websocket, "INVALID_MSG_TYPE", f"Invalid Message Type: {message['type']}")
                    continue

                # 执行处理逻辑
                try:
                    client_request = ClientRequest(**message['payload'])
                except ValueError as e:
                    await send_error(websocket, "VALIDATION_ERROR", str(e))
                    continue
                try:
                    resp = process_query(client_request)
                except Exception as e:
                    logging.error(f'处理查询失败: {str(e)}')
                    await send_error(websocket, "PROCESS_ERROR", f"处理失败: {str(e)}")

                # 构造返回消息
                respond_msg = {
                    "type": "assistant_response",
                    "message_id": message['message_id'],
                    "status": "success",
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
                try:
                    ack = await asyncio.wait_for(websocket.receive_json(), timeout = 30)
                    if ack.get('message_id') == respond_msg['message_id']:
                        print(f"[确认送达] 消息ID: {respond_msg['message_id']}")
                    else:
                        print("ACK不匹配")

                except asyncio.TimeoutError:
                    print("[未收到ACK] 消息可能没有送达")

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

async def send_error(websocket: WebSocket, code: str, detail: str = None):
    # 有一个值得考虑的问题，此处没有附带msg_id，虽然是因为解析错误导致没有可以获取的message_id...
    # 但是这样，前端要怎么知道是哪条信息解析出错了呢？
    error_msg = {
        "type": "error",
        "code": code,
        "message": "内部服务器出错。" if code == "SERVER_ERROR" else "请求格式出错。"
        # 错误类型后续最好整理一下，暂时考虑的只有这两种。
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
    uvicorn.run(app, host = "0.0.0.0", port = 8000, reload = True)
    # import uvloop
    # uvloop.install()