#!/usr/bin/env bash
set -euo pipefail

# 仓库历史中包含已跟踪的 .pyc 文件；禁止部署过程改写这些二进制文件。
export PYTHONDONTWRITEBYTECODE=1

# ---------------------------------------------------------------------------
# LLMGal 后端环境一键部署
#
# 前置：Python 3.11–3.14（推荐当前机器已安装的最高兼容版本）。
#
# 用法：
#   ./scripts/setup_env.sh                 # 仅后端运行时依赖
#   ./scripts/setup_env.sh --with-test     # 额外安装 backend/requirements-test.txt
#   ./scripts/setup_env.sh --with-frontend # 额外执行前端 npm ci
#   LLMGAL_PYTHON=/path/to/python3.14 ./scripts/setup_env.sh   # 指定基座解释器
#   LLMGAL_ENV_BACKEND=/path/to/venv  ./scripts/setup_env.sh   # 指定虚拟环境目录
#
# 复刻本机 vue-fastapi(Conda) 环境的等价手动步骤见文件底部注释。
# ---------------------------------------------------------------------------

WITH_TEST=0
WITH_FRONTEND=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-test) WITH_TEST=1 ;;
    --with-frontend) WITH_FRONTEND=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
  shift
done

PROJECT_ROOT="${LLMGAL_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${LLMGAL_ENV_BACKEND:-${PROJECT_ROOT}/backend/.venv}"

# MSYS/Git Bash 的 /f/... 路径原生 Windows 解释器不认，需转成 F:/... 形式。
to_native() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s\n' "$1"
  fi
}
PROJECT_ROOT_NATIVE="$(to_native "${PROJECT_ROOT}")"
VENV_DIR_NATIVE="$(to_native "${VENV_DIR}")"
BACKEND_NATIVE="$(to_native "${PROJECT_ROOT}/backend")"

# 定位虚拟环境内解释器（兼容 POSIX bin/ 与 Windows Scripts/）
venv_python() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    printf '%s\n' "${VENV_DIR}/bin/python"
  elif [[ -x "${VENV_DIR}/Scripts/python.exe" ]]; then
    printf '%s\n' "${VENV_DIR}/Scripts/python.exe"
  fi
}

# 版本断言：基础依赖支持 3.11–3.14。
assert_supported_python() {
  if ! "$@" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)' >/dev/null 2>&1; then
    echo "解释器 [$*] 不在支持范围 Python 3.11–3.14 内，拒绝继续。" >&2
    exit 1
  fi
}

# 解析用于建环境的基座解释器（命令名可能带参数，用数组承载）
resolve_base_python() {
  if [[ -n "${LLMGAL_PYTHON:-}" ]]; then
    BASE_PY=("${LLMGAL_PYTHON}")
    return
  fi
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1 \
       && "${candidate}" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)' >/dev/null 2>&1; then
      BASE_PY=("${candidate}")
      return
    fi
  done
  for candidate in 3.14 3.13 3.12 3.11; do
    if command -v py >/dev/null 2>&1 \
       && py -"${candidate}" -c 'import sys' >/dev/null 2>&1; then
      BASE_PY=(py -"${candidate}")
      return
    fi
  done
  echo "未找到 Python 3.11–3.14 解释器。请安装兼容版本，或通过 LLMGAL_PYTHON 指定解释器路径。" >&2
  exit 1
}

VENV_PY="$(venv_python || true)"

if [[ -z "${VENV_PY}" ]]; then
  resolve_base_python
  assert_supported_python "${BASE_PY[@]}"
  echo "[环境] 创建虚拟环境：${VENV_DIR}"
  "${BASE_PY[@]}" -m venv "${VENV_DIR_NATIVE}"
  VENV_PY="$(venv_python)"
fi

if [[ -z "${VENV_PY}" ]]; then
  echo "已在 ${VENV_DIR} 创建虚拟环境，但无法定位其中的解释器，请检查 venv 是否创建成功。" >&2
  exit 1
fi

assert_supported_python "${VENV_PY}"

echo "[环境] 使用解释器：$(${VENV_PY} --version)"
echo "[环境] 升级 pip ..."
"${VENV_PY}" -m pip install --upgrade pip

echo "[依赖] 安装 backend/requirements.txt"
"${VENV_PY}" -m pip install -r "${BACKEND_NATIVE}/requirements.txt"

# 火山旧版图像 SDK 不自动安装：其上游依赖在 Python 3.14 不兼容。
# 默认 zhipu 图像、文本模型、TTS 和模块二 AI 测试均不需要该 SDK。

if [[ "${WITH_TEST}" -eq 1 ]]; then
  echo "[依赖] 安装 backend/requirements-test.txt"
  "${VENV_PY}" -m pip install -r "${BACKEND_NATIVE}/requirements-test.txt"
fi

# .env：缺失时从 .env.example 复制（仅模板，密钥需用户自行填写）
if [[ ! -f "${PROJECT_ROOT}/backend/.env" && -f "${PROJECT_ROOT}/backend/.env.example" ]]; then
  cp "${PROJECT_ROOT}/backend/.env.example" "${PROJECT_ROOT}/backend/.env"
  echo "[配置] 已复制 .env.example -> backend/.env，请填入你的 API 密钥（勿提交）。"
fi

if [[ "${WITH_FRONTEND}" -eq 1 ]]; then
  echo "[前端] npm ci ..."
  ( cd "${PROJECT_ROOT}/frontend" && npm ci )
fi

echo
echo "=== 部署完成 ==="
echo "后端启动："
echo "  cd backend && source ${VENV_DIR}/bin/activate   # Windows: ${VENV_DIR}\\Scripts\\activate"
echo "  python -m uvicorn Connect:app --reload --host 127.0.0.1 --port 8000"
if [[ "${WITH_FRONTEND}" -ne 1 ]]; then
  echo "前端依赖未安装，按需执行：  cd frontend && npm ci && npm run dev"
fi

# ---------------------------------------------------------------------------
# 复刻本机 vue-fastapi(Conda) 环境的等价手动步骤：
#   conda create -n vue-fastapi python=3.14 -y
#   conda activate vue-fastapi
#   pip install -r backend/requirements.txt
#   # 测试依赖：
#   pip install -r backend/requirements-test.txt
# ---------------------------------------------------------------------------
