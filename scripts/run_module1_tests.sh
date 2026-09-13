#!/usr/bin/env bash
set -euo pipefail

# 仓库历史中包含已跟踪的 .pyc 文件；禁止测试运行改写这些二进制文件。
export PYTHONDONTWRITEBYTECODE=1

# LLMGAL_TEST_ROOT / LLMGAL_TEST_VENV 仅用于隔离验证，不设置时取脚本上级目录与 .venv-module1。
PROJECT_ROOT="${LLMGAL_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${LLMGAL_TEST_VENV:-${PROJECT_ROOT}/.venv-module1}"

# Git Bash / MSYS 的 /f/... 形式路径原生 Windows 解释器不认，
# 需要传给原生解释器的参数一律先转成 F:/... 形式。
to_native() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s\n' "$1"
  fi
}
PROJECT_ROOT_NATIVE="$(to_native "${PROJECT_ROOT}")"
VENV_DIR_NATIVE="$(to_native "${VENV_DIR}")"

# ---------------------------------------------------------------------------
# 1. 定位虚拟环境内的解释器：兼容 POSIX 的 bin/ 与 Windows 的 Scripts/
# ---------------------------------------------------------------------------
venv_python() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    printf '%s\n' "${VENV_DIR}/bin/python"
  elif [[ -x "${VENV_DIR}/Scripts/python.exe" ]]; then
    printf '%s\n' "${VENV_DIR}/Scripts/python.exe"
  fi
}

# ---------------------------------------------------------------------------
# 2. 版本断言：本项目 fastapi==0.95.1 + pydantic==1.10.7 在 3.12/3.13 上
#    导入即失败（ForwardRef._evaluate 签名变更），解释器必须钉死 3.11。
# ---------------------------------------------------------------------------
assert_py311() {
  if ! "$@" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' >/dev/null 2>&1; then
    echo "解释器 [$*] 不是 Python 3.11，拒绝继续。" >&2
    echo "fastapi==0.95.1 + pydantic==1.10.7 在 Python 3.12/3.13 上收集阶段即报 TypeError。" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# 3. 解析用于建环境的基座解释器（命令名可能带参数，用数组承载）
# ---------------------------------------------------------------------------
resolve_base_python() {
  if [[ -n "${LLMGAL_TEST_PYTHON:-}" ]]; then
    BASE_PY=("${LLMGAL_TEST_PYTHON}")
    return
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    BASE_PY=(python3.11)
  elif command -v py >/dev/null 2>&1 && py -3.11 -c 'import sys' >/dev/null 2>&1; then
    BASE_PY=(py -3.11)
  elif command -v python3 >/dev/null 2>&1 \
       && python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' >/dev/null 2>&1; then
    BASE_PY=(python3)
  else
    echo "未找到 Python 3.11 解释器。请安装 Python 3.11，或在运行前指定：" >&2
    echo "  LLMGAL_TEST_PYTHON=/c/Users/<you>/AppData/Local/Programs/Python/Python311/python.exe" >&2
    echo "  LLMGAL_TEST_PYTHON=\"py -3.11\"   # Windows 上也可用 py 启动器" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# 4. 依赖自愈：venv 可能已存在但依赖不全（例如上次运行被中断留下的空壳）
# ---------------------------------------------------------------------------
venv_ready() {
  local py="$1"
  [[ -n "${py}" ]] || return 1
  "${py}" -c 'import pytest, fastapi, pydantic, requests, websockets' >/dev/null 2>&1
}

VENV_PY="$(venv_python || true)"

if [[ -z "${VENV_PY}" ]]; then
  resolve_base_python
  assert_py311 "${BASE_PY[@]}"
  "${BASE_PY[@]}" -m venv "${VENV_DIR_NATIVE}"
  VENV_PY="$(venv_python)"
fi

if [[ -z "${VENV_PY}" ]]; then
  echo "已在 ${VENV_DIR} 创建虚拟环境，但无法定位其中的解释器，请检查 venv 是否创建成功。" >&2
  exit 1
fi

assert_py311 "${VENV_PY}"

if ! venv_ready "${VENV_PY}"; then
  echo "[环境] ${VENV_DIR} 缺少测试依赖，开始安装 backend/requirements-test.txt"
  "${VENV_PY}" -m pip install --upgrade pip
  "${VENV_PY}" -m pip install -r "${PROJECT_ROOT_NATIVE}/backend/requirements-test.txt"
  if ! venv_ready "${VENV_PY}"; then
    echo "依赖安装后仍无法导入测试依赖，请检查网络或 requirements-test.txt。" >&2
    exit 1
  fi
fi

mkdir -p "${PROJECT_ROOT}/artifacts/test-results"
cd "${PROJECT_ROOT}/backend"

"${VENV_PY}" -m pytest \
  tests \
  --junitxml="${PROJECT_ROOT_NATIVE}/artifacts/test-results/module1-junit.xml" \
  --cov=Connect \
  --cov=Integration \
  --cov=Text \
  --cov=Voice \
  --cov=Image \
  --cov-report=term-missing \
  "$@" | tee "${PROJECT_ROOT}/artifacts/test-results/pytest-output.txt"
