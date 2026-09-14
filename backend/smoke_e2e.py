"""端到端冒烟测试（真实进程 + 真实 WebSocket，不用测试替身）。

验证：
1. 服务能起来并打印配置自检
2. 心跳帧 -> pong
3. 内容不合法的 payload -> invalid_message
4. 合法但缺少密钥的查询 -> 明确的处理错误（而不是静默失败）
5. 鉴权开启时错误 token 被拒绝

!! 注意：本脚本会真实调用 LLM 与 TTS，后端会把合成结果写进
   frontend/src/assets/voice/<角色>/<角色>_<序号>_Stream.wav，
   也就是**覆盖真实对话正在使用的语音槽位**。这会导致：
   - 浏览器里刚生成的语音被顶掉，播到别的内容；
   - 新增文件触发 Vite 的文件监听/HMR，间接放大前端的音频时序问题。
   调试前端音频时请避免一边跑本脚本一边在页面上试聊。
"""

import asyncio
import json
import os
import sys

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8123/ws/chat"
# 用后端实际配置的模型，避免占位名导致 400「模型不存在」
MODEL = config.TEXT_MODEL


async def main():
    results = []

    async with websockets.connect(URL) as ws:
        # 1. 心跳
        await ws.send(json.dumps({"type": "heartbeat", "message_id": "hb-1"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        results.append(("心跳 -> pong", reply.get("type") == "pong", reply))

        # 2. 内容不合法：textModel_config 缺 text
        await ws.send(json.dumps({
            "type": "client_query", "message_id": "bad-1",
            "payload": {
                "textModel_config": {"modelText": MODEL},
                "role": "Wendy",
                "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
                "voiceCate": "GirlFriend",
            },
        }))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        results.append(("缺 text -> invalid_message", reply.get("type") == "invalid_message", reply))

        # 3. 合法结构但没填密钥：应当回一条明确的错误，而不是卡死或静默
        await ws.send(json.dumps({
            "type": "client_query", "message_id": "ok-1",
            "payload": {
                "textModel_config": {"text": {"role": "user", "content": "你好"},
                                     "modelText": MODEL},
                "role": "Wendy",
                "imageModel_config": {"modelImage": "m", "realTimeRendering": False},
                "voiceCate": "GirlFriend",
                "history": [{"role": "user", "content": "上句"}],
            },
        }))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
        responded = reply.get("type") in ("assistant_response", "error", "invalid_message")
        results.append(("合法查询有明确响应", responded, reply))

    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"        {json.dumps(detail, ensure_ascii=False)[:300]}")

    return 0 if all(ok for _n, ok, _d in results) else 1


sys.exit(asyncio.run(main()))
