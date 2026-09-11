from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# 生产模块会在导入阶段加载外部 SDK。单元测试不访问这些服务，因此在开发机
# 没有安装 SDK 时提供最小 Stub，使测试环境只需安装 requirements-test.txt。
try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

try:
    import volcengine.visual  # noqa: F401
except ModuleNotFoundError:
    volcengine_stub = types.ModuleType("volcengine")
    visual_stub = types.ModuleType("volcengine.visual")
    visual_service_stub = types.ModuleType("volcengine.visual.VisualService")

    class VisualServiceStub:
        pass

    visual_stub.VisualService = VisualServiceStub
    visual_service_stub.VisualService = VisualServiceStub
    volcengine_stub.visual = visual_stub
    sys.modules["volcengine"] = volcengine_stub
    sys.modules["volcengine.visual"] = visual_stub
    sys.modules["volcengine.visual.VisualService"] = visual_service_stub


@pytest.fixture(autouse=True)
def block_real_external_calls(monkeypatch):
    """任何漏掉的 HTTP/WebSocket 外部调用都应立即使测试失败。"""

    def blocked(*_args, **_kwargs):
        raise AssertionError("单元测试禁止访问真实外部服务")

    async def blocked_async(*_args, **_kwargs):
        raise AssertionError("单元测试禁止访问真实外部服务")

    monkeypatch.setattr("requests.sessions.Session.request", blocked)
    monkeypatch.setattr("websockets.connect", blocked_async)
