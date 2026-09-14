#!/usr/bin/env bash
set -euo pipefail

# macOS/Linux compatibility wrapper. The Python launcher owns all platform-
# specific virtual-environment handling, including stale-interpreter recovery.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${LLMGAL_TEST_PYTHON:-}" ]]; then
  exec "${LLMGAL_TEST_PYTHON}" "${SCRIPT_DIR}/run_module1_tests.py" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "${SCRIPT_DIR}/run_module1_tests.py" "$@"
fi

exec python "${SCRIPT_DIR}/run_module1_tests.py" "$@"
