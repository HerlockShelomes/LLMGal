from __future__ import annotations

import sys
import types
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# 旧版生产代码在导入阶段加载第三方 SDK。模块一测试不会调用真实外部服务，
# 因此在测试环境没有安装这些 SDK 时提供最小 Stub，避免产生网络或费用。
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
