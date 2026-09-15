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
def force_prod_mode(monkeypatch, tmp_path):
    """单元测试一律跑在「正式版」口径。

    Mock 版会把整条 AI 链路旁路掉（Integration 直接返回状态回执），
    那些断言真实调用行为的用例会「通过得毫无意义」。而模式开关是落盘的
    （backend/runtime_mode.json），本机手工切过一次 mock 就会污染整轮测试。
    这里把开关文件指到一个不存在的临时路径、并把默认值钉成 prod，
    等效于「从未切换过」—— 不依赖 `config` 的内部实现。
    """
    import config

    monkeypatch.setattr(config, "MODE_PATH", str(tmp_path / "runtime_mode.json"))
    monkeypatch.setattr(config, "_initial_mode", config.MODE_PROD)
    assert config.get_mode() == config.MODE_PROD
    assert not config.is_mock()


@pytest.fixture(autouse=True)
def block_real_external_calls(monkeypatch):
    """任何漏掉的 HTTP/WebSocket 外部调用都应立即使测试失败。"""

    def blocked(*_args, **_kwargs):
        raise AssertionError("单元测试禁止访问真实外部服务")

    async def blocked_async(*_args, **_kwargs):
        raise AssertionError("单元测试禁止访问真实外部服务")

    monkeypatch.setattr("requests.sessions.Session.request", blocked)
    monkeypatch.setattr("websockets.connect", blocked_async)
