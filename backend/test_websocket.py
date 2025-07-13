import json
import pytest
from websockets import connect
from Connect import websocket_chat
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_websocket_basic():
    async with connect("ws://localhost:8000/ws/chat") as ws:
        # 发送测试消息
        await ws.send(json.dumps({
            "type": "client_query",
            "message_id": "test_message_id_1234",
            "payload": {
                "textModel_config": {
                    "text": {"user": "你好，今天过得如何？"},
                    "modelText": "deepseek-ai/DeepSeek-V3",
                },
                "role": "GirlProgrammer",
                "imageModel_config": {
                    "modelImage": "high_aes_ip_v20",
                    "realTimeRendering": True
                },
                "voiceCate": "ElderSister"
            }
        }))
        raw_response = await ws.recv()
        response_data = json.loads(raw_response)
        print(raw_response)
        # 结构化验证消息
        assert "type" in response_data and response_data['type'] == "assistant_response"
        assert "message_id" in response_data and response_data['message_id'] == "test_message_id_1234"
        assert "status" in response_data and response_data['status'] == "success"
        assert "response" in response_data['payload']
        assert "emotion" in response_data['payload'] and response_data['payload']['emotion'] in ["neutral", "happy",
                                                                           "sad", "fear",
                                                                           "angry","surprised",
                                                                           "shy"]
        assert "index" in response_data['payload'] and 0 <= int(response_data['payload']['index']) <= 9
        assert "metrics" in response_data['payload'] and isinstance(response_data['payload']['metrics'], dict)

        # metrics再度校验
        metrics = response_data['payload']['metrics']
        assert "time_cost" in metrics and metrics['time_cost'] > 0
        assert "tokens_used" in metrics and metrics['tokens_used'] > 0

        # 图片地址校验
        if "imageUrl" in response_data['payload']:
            assert response_data['payload']["imageUrl"].startswith('http')
            # assert ".png" in response_data['payload']["imageUrl"] or ".jpg" in response_data['payload']["imageUrl"]

        # 汉字有效性检测
        import re
        assert re.search(r'[\u4e00-\u9fff]{5,}', response_data['payload']['response'])

        # import time
        # start = time.time()
        # await ws.send(json.dumps({"type": "ping"}))
        # await ws.recv()
        # assert (time.time() - start) < 1.5

# @pytest.mark.asyncio
# async def test_error_handling():
#     async with connect("ws://localhost:8000/ws/chat") as ws:
#         # 发送异常数据
#         await ws.send("invalid Json")
#         response = await ws.recv()
#
#         # 验证错误码
#         assert "400" in response
#         assert "message" in response
#
# @pytest.mark.asyncio
# async def test_websocket_connection():
#     # 初始化应用
#     from Connect import app
#     client = TestClient(app)
#
#     # 异步测试逻辑
#     with client.websocket_connect("/ws/chat") as websocket:
#         data = websocket.receive_text()
#         assert data == "Connected"
#         websocket.send_text("Ping")
#         response = websocket.receive_text()
#         assert response == "Pong"
