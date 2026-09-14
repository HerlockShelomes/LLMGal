#!/usr/bin/env python3
"""Cross-platform launcher for the isolated module-one backend tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


MINIMUM_PYTHON = (3, 9)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / ".venv-module1"
REQUIREMENTS = PROJECT_ROOT / "backend" / "requirements-test.txt"
RESULT_DIR = PROJECT_ROOT / "artifacts" / "test-results"


def venv_python(venv_dir: Path) -> Path:
    """Return the platform-specific Python executable in a virtual environment."""
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run isolated module-one tests on Windows, macOS, or Linux."
    )
    parser.add_argument(
        "--python",
        dest="python_command",
        help="Python interpreter used to create the test virtual environment.",
    )
    parser.add_argument(
        "--recreate-venv",
        action="store_true",
        help="Discard the generated module-one virtual environment before running.",
    )
    return parser.parse_known_args(argv)


def resolve_python(command: str | None) -> Path:
    requested = command or os.environ.get("LLMGAL_TEST_PYTHON") or sys.executable
    candidate = Path(requested).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    resolved = shutil.which(requested)
    if resolved:
        return Path(resolved).resolve()

    raise RuntimeError(
        f"找不到 Python 解释器：{requested}。可通过 --python 或 "
        "LLMGAL_TEST_PYTHON 指定解释器。"
    )


def python_info(python: Path) -> dict[str, object]:
    command = (
        "import json, sys; "
        "print(json.dumps({'version': list(sys.version_info[:3]), 'executable': sys.executable}))"
    )
    completed = subprocess.run(
        [str(python), "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def validate_python(python: Path) -> tuple[int, int, int]:
    try:
        info = python_info(python)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法执行 Python 解释器：{python}") from exc

    version = tuple(int(value) for value in info["version"])
    if version[:2] < MINIMUM_PYTHON:
        minimum = ".".join(str(value) for value in MINIMUM_PYTHON)
        current = ".".join(str(value) for value in version)
        raise RuntimeError(f"Python {current} 过旧；模块一测试要求 Python {minimum}+。")
    return version


def recreate_venv_if_needed(
    requested_python: Path, requested_version: tuple[int, int, int], force: bool
) -> Path:
    environment_python = venv_python(VENV_DIR)
    reason = ""

    if force:
        reason = "已指定 --recreate-venv"
    elif not environment_python.exists():
        reason = "测试虚拟环境不存在"
    else:
        try:
            environment_version = tuple(int(value) for value in python_info(environment_python)["version"])
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            reason = "现有测试虚拟环境不可用"
        else:
            if environment_version[:2] != requested_version[:2]:
                old = ".".join(str(value) for value in environment_version[:2])
                new = ".".join(str(value) for value in requested_version[:2])
                reason = f"虚拟环境使用 Python {old}，当前启动器使用 Python {new}"

    if reason:
        if VENV_DIR.exists():
            print(f"重建 {VENV_DIR.name}：{reason}")
            shutil.rmtree(VENV_DIR)
        else:
            print(f"创建 {VENV_DIR.name}：{reason}")
        subprocess.run([str(requested_python), "-m", "venv", str(VENV_DIR)], check=True)

    return venv_python(VENV_DIR)


def requirements_digest() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def install_requirements(python: Path) -> None:
    marker = VENV_DIR / ".module1-requirements.sha256"
    current_digest = requirements_digest()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == current_digest:
        return

    print("安装或更新模块一测试依赖...")
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True
    )
    marker.write_text(f"{current_digest}\n", encoding="utf-8")


def verify_test_runtime(python: Path) -> None:
    """Fail early with a dependency error instead of a pytest collection error."""
    command = "import fastapi, pydantic; print(f'fastapi={fastapi.__version__}; pydantic={pydantic.VERSION}')"
    try:
        completed = subprocess.run(
            [str(python), "-c", command],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        details = getattr(exc, "stderr", "") or ""
        raise RuntimeError(
            "测试依赖无法导入；请使用 --recreate-venv 重建测试环境。"
            f"\n{details.strip()}"
        ) from exc
    print(f"测试依赖就绪：{completed.stdout.strip()}")


def run_pytest(python: Path, pytest_args: Sequence[str]) -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RESULT_DIR / "pytest-output.txt"
    junit_path = RESULT_DIR / "module1-junit.xml"
    command = [
        str(python),
        "-m",
        "pytest",
        "tests",
        f"--junitxml={junit_path}",
        "--cov=Connect",
        "--cov=Integration",
        "--cov=Text",
        "--cov=Voice",
        "--cov=Image",
        "--cov-report=term-missing",
        *pytest_args,
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    print(f"运行模块一测试：{' '.join(command)}")
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT / "backend",
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log_file.write(line)
        return process.wait()


def main(argv: Sequence[str] | None = None) -> int:
    options, pytest_args = parse_args(argv or sys.argv[1:])
    try:
        requested_python = resolve_python(options.python_command)
        requested_version = validate_python(requested_python)
        version_label = ".".join(str(value) for value in requested_version)
        print(f"使用 Python {version_label}: {requested_python}")
        test_python = recreate_venv_if_needed(
            requested_python, requested_version, options.recreate_venv
        )
        install_requirements(test_python)
        verify_test_runtime(test_python)
        return run_pytest(test_python, pytest_args)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"模块一测试启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
