#!/usr/bin/env python3
"""跨平台初始化 LLMGal 本地开发环境。

本脚本只创建/更新项目生成物：backend/.venv、backend/.env（若缺失）和
frontend/node_modules；不会覆盖已有 .env，也不会写入任何密钥。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VENV_DIR = BACKEND_DIR / ".venv"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
MIN_PYTHON = (3, 11)
MAX_PYTHON_EXCLUSIVE = (3, 15)


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化 LLMGal 本地后端和前端环境。")
    parser.add_argument(
        "--python",
        dest="python_command",
        default=sys.executable,
        help="用于创建后端虚拟环境的 Python 解释器（默认：当前解释器）。",
    )
    parser.add_argument("--backend-only", action="store_true", help="只初始化后端。")
    parser.add_argument("--frontend-only", action="store_true", help="只初始化前端。")
    parser.add_argument("--recreate-venv", action="store_true", help="重新创建 backend/.venv。")
    return parser.parse_args()


def resolve_python(command: str) -> Path:
    supplied = Path(command).expanduser()
    if supplied.is_file():
        return supplied.resolve()
    located = shutil.which(command)
    if located:
        return Path(located).resolve()
    raise RuntimeError(f"找不到 Python 解释器：{command}")


def python_version(python: Path) -> tuple[int, int, int]:
    command = "import json, sys; print(json.dumps(list(sys.version_info[:3])))"
    try:
        completed = subprocess.run(
            [str(python), "-c", command], check=True, capture_output=True, text=True
        )
        version = tuple(json.loads(completed.stdout))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法执行 Python：{python}") from error
    return version  # type: ignore[return-value]


def verify_python(python: Path) -> tuple[int, int, int]:
    version = python_version(python)
    if version[:2] < MIN_PYTHON or version[:2] >= MAX_PYTHON_EXCLUSIVE:
        raise RuntimeError(
            "当前解释器为 Python {}.{}.{}；LLMGal 支持 Python 3.11–3.14。"
            "请安装兼容版本后通过 --python 指定。".format(*version)
        )
    return version


def ensure_backend_venv(python: Path, requested_version: tuple[int, int, int], force: bool) -> Path:
    target = venv_python()
    recreate_reason = ""
    if force:
        recreate_reason = "已指定 --recreate-venv"
    elif not target.exists():
        recreate_reason = "虚拟环境不存在"
    else:
        try:
            existing_version = python_version(target)
        except RuntimeError:
            recreate_reason = "现有虚拟环境不可用"
        else:
            if existing_version[:2] != requested_version[:2]:
                recreate_reason = "现有虚拟环境的 Python 版本不同"

    if recreate_reason:
        if VENV_DIR.exists():
            print(f"重建 backend/.venv：{recreate_reason}")
            shutil.rmtree(VENV_DIR)
        else:
            print("创建 backend/.venv")
        subprocess.run([str(python), "-m", "venv", str(VENV_DIR)], check=True)
    return target


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_backend_dependencies(python: Path) -> None:
    marker = VENV_DIR / ".llmgal-requirements.sha256"
    current = digest(REQUIREMENTS)
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == current:
        print("后端依赖已是最新，跳过安装。")
        return
    print("安装后端运行时依赖...")
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
    marker.write_text(current + "\n", encoding="utf-8")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        print("保留现有 backend/.env（不会覆盖本地配置）。")
        return
    if not ENV_EXAMPLE.exists():
        raise RuntimeError("缺少 backend/.env.example，无法生成本地配置模板。")
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    print("已创建 backend/.env；请先填写文本模型和 TTS 的开发密钥。")


def npm_command() -> str:
    command = "npm.cmd" if os.name == "nt" else "npm"
    if not shutil.which(command):
        raise RuntimeError("未找到 npm；请安装 Node.js 18 或更高版本后重新执行。")
    return command


def install_frontend_dependencies() -> None:
    command = npm_command()
    print("安装前端依赖（npm ci）...")
    subprocess.run([command, "ci"], cwd=FRONTEND_DIR, check=True)


def main() -> int:
    options = parse_args()
    if options.backend_only and options.frontend_only:
        print("不能同时指定 --backend-only 与 --frontend-only。", file=sys.stderr)
        return 2
    try:
        if not options.frontend_only:
            requested = resolve_python(options.python_command)
            version = verify_python(requested)
            print(f"后端使用 Python {'.'.join(map(str, version))}: {requested}")
            backend_python = ensure_backend_venv(requested, version, options.recreate_venv)
            install_backend_dependencies(backend_python)
            ensure_env_file()
        if not options.backend_only:
            install_frontend_dependencies()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"初始化失败：{error}", file=sys.stderr)
        return 1
    print("\n初始化完成。下一步：")
    print("  1. 检查并填写 backend/.env 中的开发密钥。")
    print("  2. 终端 A：python scripts/start_backend.py")
    print("  3. 终端 B：npm --prefix frontend run dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
