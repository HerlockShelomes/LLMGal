#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-module1"
PYTHON_BIN="${LLMGAL_TEST_PYTHON:-python3.11}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "未找到 ${PYTHON_BIN}。请安装 Python 3.11，或通过 LLMGAL_TEST_PYTHON 指定解释器。" >&2
    exit 1
  fi
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/backend/requirements-test.txt"
fi

mkdir -p "${PROJECT_ROOT}/artifacts/test-results"
cd "${PROJECT_ROOT}"

"${VENV_DIR}/bin/python" -m pytest \
  backend/tests \
  --junitxml="${PROJECT_ROOT}/artifacts/test-results/module1-junit.xml" \
  --cov=Connect \
  --cov=Integration \
  --cov=Text \
  --cov=Voice \
  --cov=Image \
  --cov-report=term-missing \
  "$@" | tee "${PROJECT_ROOT}/artifacts/test-results/pytest-output.txt"
