#!/usr/bin/env python3
"""从仓库任意位置以已初始化的后端虚拟环境启动 LLMGal。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python"
)


def main() -> int:
    if not VENV_PYTHON.exists():
        print("未找到 backend/.venv。请先运行：python scripts/setup_local.py", file=sys.stderr)
        return 1
    try:
        return subprocess.run([str(VENV_PYTHON), "Connect.py"], cwd=BACKEND_DIR).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
