# `scripts/run_module1_tests.sh` 环境适配指南

> 审计对象：`docs/module1/LLMGal_backend_34_test_cases.md`、`scripts/run_module1_tests.sh`、`backend/`（依赖清单、pytest 配置、测试代码、被测源码）。
> 审计模式：**只读**。未修改任何已有文件。本文所有结论均来自本机实测，命令与输出摘要在文末「证据清单」。
> 结论有效期：2026-09-11，本机 Windows 环境。

---

## 一、结论

1. **当前环境下，`scripts/run_module1_tests.sh` 不能正常运行。**
2. **第一个失败点在第 12–14 行**：`command -v python3.11` 找不到这个命令名，脚本打印提示后 `exit 1`。第 16 行之后的逻辑（建 venv、装依赖、跑 pytest）**一行都执行不到**。
3. **即使绕过第一关，第二关也必然失败**：脚本第 11 / 17 / 24 行假设虚拟环境是 POSIX 布局 `<venv>/bin/python`，而 Windows 的 `python -m venv` 只产出 `<venv>\Scripts\python.exe`。仓库里现存的 `.venv-module1` 就是反例——只有 `Scripts/`，没有 `bin/`。
4. **被测对象本身没有问题。** 用本机 Python 3.11.9 在隔离目录里按 `requirements-test.txt` 装齐依赖后原样跑一遍：**32 passed, 2 xfailed in 1.6s**。所以「跑不起来」是启动脚本的平台假设问题，不是测试或源码的问题。
5. **解释器必须钉死在 3.11。** 实测 Python 3.12.8 与 3.13.14 都在**收集阶段**就崩，一个用例都跑不到：`fastapi 0.95.1 + pydantic 1.10.7` 触发 `TypeError: ForwardRef._evaluate() missing 1 required keyword-only argument: 'recursive_guard'`。

---

## 二、环境事实清单（实测）

| 项 | 实测结果 | 对脚本的影响 |
|---|---|---|
| 操作系统 | Windows（win32），仓库位于 `F:\LLMGal` | 决定 venv 布局是 `Scripts/` |
| Shell | Git Bash 5.2.26；`dirname` / `tee` / `mkdir` 均在 `/usr/bin` | shell 语法层没问题，不是瓶颈 |
| `python3.11` | PATH 中**不存在** | **致命**：脚本 `exit 1` |
| `python3` | 仅 WorkBuddy 托管目录提供（3.13.12）；`C:\Program Files\Python312`、`...\Python311` 下都只有 `python.exe`，没有 `python3.exe` | 不能把 `python3` 当 3.11 的替代品 |
| 可用的 3.11 基座 | ① `C:\Users\Lenovo\AppData\Local\Programs\Python\Python311\python.exe` = 3.11.9（`py -3.11` 指向它）② `E:\Anaconda\envs\vue-fastapi\python.exe` = 3.11.13 | 基座是有的，只是名字不叫 `python3.11` |
| `.venv-module1` | **已存在**，但 `pyvenv.cfg` 记录基座为 `E:\Anaconda\envs\vue-fastapi`（3.11.13），只有 `Scripts/`、无 `bin/`，`site-packages` 里只有 `pip 24.0` + `setuptools 65.5.0` | 上次中断留下的**空壳**，不含任何测试依赖 |
| `artifacts/` | 不存在 | 脚本第 21 行会创建，正常 |
| `backend/__pycache__/*.pyc` | 7 个 `.cpython-311.pyc` **已被 git 跟踪** | 依赖 `PYTHONDONTWRITEBYTECODE=1` 保护，脚本这一点做对了 |
| 网络 | PyPI 可达 | pip 安装无障碍 |

---

## 三、逐行审计：断在哪、为什么

### 断点 1 —— 解释器探测（第 9、12–14 行）【致命，当前唯一触发点】

```bash
PYTHON_BIN="${LLMGAL_TEST_PYTHON:-python3.11}"
...
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "未找到 ${PYTHON_BIN}。请安装 Python 3.11，或通过 LLMGAL_TEST_PYTHON 指定解释器。" >&2
    exit 1
  fi
```

- 实测：`command -v python3.11` → 空。
- 因此脚本走到 `exit 1`。**这就是用户实际看到的失败**。
- 根因：`python3.11` 是 POSIX 命名习惯。Windows 上正确的调用方式是 `py -3.11`，或者写完整 exe 路径。
- **脚本自带的逃生口不够用**：`LLMGAL_TEST_PYTHON` 只能放**单个路径**。设成 `LLMGAL_TEST_PYTHON="py -3.11"` 会失败——因为 `command -v "py -3.11"` 会把整串当一个命令名去找，后面 `"${PYTHON_BIN}" -m venv` 也会尝试执行一个名叫 `py -3.11` 的文件。

### 断点 2 —— venv 布局假设（第 11、16–18、24 行）【致命，被断点 1 掩盖】

```bash
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/backend/requirements-test.txt"
fi
...
"${VENV_DIR}/bin/python" -m pytest tests ...
```

- Windows 的 `venv` 产出 `Scripts\python.exe`，**永远不会**产出 `bin/python`。
- 后果 A：第 11 行守卫恒为真 → 每次执行都会重建 venv 并重装依赖（幂等，但每次都要联网、多花几十秒）。
- 后果 B：第 17 行 `"$VENV_DIR/bin/python" -m pip install ...` → `No such file or directory`；因为脚本开头有 `set -euo pipefail`，整脚本立即中断（退出码 127），第 18 行及之后全部不执行。
- 后果 C：即使侥幸走到第 24 行，pytest 同样起不来。

### 断点 3 —— 现存 `.venv-module1` 是空壳【非致命，但会造成误判】

- 它是上次运行中断留下的：基座 `E:\Anaconda\envs\vue-fastapi`（3.11.13，该路径存在），但 `site-packages` 里只有 pip/setuptools。
- 因为断点 2 的守卫判断失效，脚本**不会**主动补装依赖 → 即便把 `bin/python` 的问题绕开，仍会 `ModuleNotFoundError: fastapi`。
- 处置：直接往里面装依赖，或删掉重建。`.venv-module1/` 已在 `.gitignore` 中，删除不影响仓库。

### 已否证项 —— 这些地方没问题，不要乱改

| 检查项 | 结论 | 依据 |
|---|---|---|
| `backend/pytest.ini` 的 `addopts = --asyncio-mode=auto` | **有效** | 解包 `pytest_asyncio-1.0.0-py3-none-any.whl`，`plugin.py` 中仍保留 `--asyncio-mode` 选项定义（含 `dest="asyncio_mode"`） |
| `--cov=Connect/Integration/Text/Voice/Image` | **有效** | 实测覆盖率报告正常输出：Connect 73% / Integration 83% / Text 76% / Image 40% / Voice 31%，TOTAL 56% |
| `mkdir -p artifacts/test-results` + `tee` | **有效** | Git Bash coreutils 齐全 |
| `PYTHONDONTWRITEBYTECODE=1` | **有效** | 跑完后 `git status --short` 为空，7 个被跟踪的 `.pyc` 未被改写 |
| `set -euo pipefail` + `\| tee` | 行为符合预期 | pytest 失败时管道整体返回非零，适合 CI 判定 |

---

## 四、解释器矩阵（实测）

| 解释器 | 结果 |
|---|---|
| Python **3.11.9**（python.org 安装版） | **32 passed, 2 xfailed in 1.6s** ✔ |
| Python **3.12.8** | 收集阶段报错 `TypeError: ForwardRef._evaluate() missing 1 required keyword-only argument: 'recursive_guard'`，0 用例执行 ✘ |
| Python **3.13.14** | 同上 ✘ |

原因链：`requirements-test.txt` 钉死 `pydantic==1.10.7`。pydantic v1 的 forward-ref 求值在 CPython 3.12 起不兼容（`typing.ForwardRef._evaluate` 新增了 keyword-only 参数 `recursive_guard`），要到 pydantic ≥ 1.10.13 才修；`fastapi==0.95.1` 的 `openapi/models.py` 恰好用字符串注解，导入即触发。

一个容易踩的坑：**`import pydantic` 在 3.13 上是通的**（我实测过），崩的是 fastapi 侧的 forward-ref 解析。所以不要用「pydantic 能 import」来推断环境可用。同理，不要因为 3.12 比 3.11 新就顺手换过去。

---

## 五、解决策略

### 策略 A（推荐）：加固脚本，让它同时认两种布局

一次性投入，之后在 Windows / WSL / Linux 上都能直接跑。改动点：

1. **解释器探测改为探测链**：`LLMGAL_TEST_PYTHON` → `python3.11` → `py -3.11` → `python3`（且校验版本）。
2. **解释器用数组承载**：因为 `py -3.11` 是「命令 + 参数」两段，用 `BASE_PY=(py -3.11)` + `"${BASE_PY[@]}"` 保证两个词都被正确传递。
3. **venv 解释器双布局探测**：先试 `bin/python`，再试 `Scripts/python.exe`。
4. **加版本断言**：拿到任何解释器后立刻断言 `sys.version_info[:2] == (3, 11)`，把「误用 3.12/3.13」拦在报错信息清晰的地方，而不是让它以一堆 pydantic 栈回溯的形式炸出来。

完整修正版见「附录 A」。**该版本已在真实 Git Bash 中实测跑通**（见证据清单 E6）。

### 策略 B（零改动，最快见效）：手工三步

不想动脚本的话，照下面做完就能跑。注意：**只设置 `LLMGAL_TEST_PYTHON` 解决不了问题**，因为 `bin/python` 的坑还在。

```bash
# 1) 用 python.org 的 3.11.9 建环境（现存 .venv-module1 是空壳，直接删掉重建最省事）
#    该目录在 .gitignore 里，删了不动仓库
rm -rf /f/LLMGal/.venv-module1
"/c/Users/Lenovo/AppData/Local/Programs/Python/Python311/python.exe" -m venv /f/LLMGal/.venv-module1

# 2) 装依赖（注意是 Scripts，不是 bin）
/f/LLMGal/.venv-module1/Scripts/python.exe -m pip install -r /f/LLMGal/backend/requirements-test.txt

# 3) 跑测试（等价于脚本第 21-33 行）
mkdir -p /f/LLMGal/artifacts/test-results
cd /f/LLMGal/backend
PYTHONDONTWRITEBYTECODE=1 /f/LLMGal/.venv-module1/Scripts/python.exe -m pytest tests \
  --junitxml=/f/LLMGal/artifacts/test-results/module1-junit.xml \
  --cov=Connect --cov=Integration --cov=Text --cov=Voice --cov=Image \
  --cov-report=term-missing \
  | tee /f/LLMGal/artifacts/test-results/pytest-output.txt
```

不想删 `.venv-module1` 也行，第 1 步跳过，直接执行第 2 步往它里面装依赖即可（它的基座是 Anaconda 3.11.13，可用）。

> 提示：`rm -rf` 只针对 `.venv-module1` 这个已被 `.gitignore` 忽略的构建产物。执行前确认路径拼写正确；不放心的话用「跳过第 1 步」的写法。

### 策略 C：在 WSL / Linux 下原样跑

脚本本来就是给 POSIX 写的，在 Linux 上 `bin/python` 布局成立，**原样可用**（前提：容器/发行版里装了 `python3.11` 与 `python3.11-venv`）。

适用场景：远端 Linux 服务器、CI runner。
说明：我**无法验证本机是否装了 WSL**——沙箱以安全策略拦截了 `wsl.exe`。所以这条只是备选，需要你自己确认。

### 策略 D：CI 侧约束（长期）

- 在 CI 配置里显式声明 `python-version: 3.11`；
- 把「依赖版本不随解释器漂移」写进 `requirements-test.txt` 的注释里，说明为什么必须 3.11；
- 可选：把 `pydantic` 升到 `1.10.13+` 以放宽解释器限制——但这会同时牵动 `fastapi 0.95.1` / `starlette 0.26.1` 的兼容面，**不建议在没有回归验证的前提下动**。

---

## 六、验收标准

修正后（策略 A 或 B）正常跑通应看到：

1. 终端末尾 `32 passed, 2 xfailed`；
2. `artifacts/test-results/module1-junit.xml` 与 `pytest-output.txt` 生成；
3. 覆盖率表包含 Connect / Image / Integration / Text / Voice 五个模块；
4. 跑完 `git status --short` 为空。

**2 个 xfail 是设计如此，不是失败**，它们用来登记当前实现与文档预期的不一致：

- `test_tc_tts_04_invalid_base64_must_not_create_audio` —— TC-TTS-04：当前实现会写入零字节音频；
- `test_tc_ex_02_nonnumeric_index_fails_after_external_side_effects` —— TC-EX-02：正则表达式先排除了非数字索引。

另外 34 条用例全部有对应实现（32 passed + 2 xfailed = 34），与 `docs/module1/LLMGal_backend_34_test_cases.md` 的数量一致。

---

## 附录 A：修正版脚本

> 相对原脚本的差异只有 4 处：解释器探测链、数组化解释器、venv 双布局探测、版本断言。
> `LLMGAL_TEST_ROOT` / `LLMGAL_TEST_VENV` 两个环境变量是为了能在隔离目录里验证而加的，不设置时行为与原来一致（取脚本上级目录与 `.venv-module1`）。
> **本指南未改动 `scripts/run_module1_tests.sh` 本身**，需要落地时告诉我即可。

```bash
#!/usr/bin/env bash
set -euo pipefail

# 仓库历史中包含已跟踪的 .pyc 文件；禁止测试运行改写这些二进制文件。
export PYTHONDONTWRITEBYTECODE=1

PROJECT_ROOT="${LLMGAL_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${LLMGAL_TEST_VENV:-${PROJECT_ROOT}/.venv-module1}"

# ---------------------------------------------------------------------------
# 1. 解析虚拟环境内的解释器：兼容 POSIX 的 bin/ 与 Windows 的 Scripts/
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
#    导入即失败（ForwardRef._evaluate 签名变更），必须钉死 3.11。
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

VENV_PY="$(venv_python || true)"

if [[ -z "${VENV_PY}" ]]; then
  resolve_base_python
  assert_py311 "${BASE_PY[@]}"
  "${BASE_PY[@]}" -m venv "${VENV_DIR}"
  VENV_PY="$(venv_python)"
  "${VENV_PY}" -m pip install --upgrade pip
  "${VENV_PY}" -m pip install -r "${PROJECT_ROOT}/backend/requirements-test.txt"
fi

assert_py311 "${VENV_PY}"

mkdir -p "${PROJECT_ROOT}/artifacts/test-results"
cd "${PROJECT_ROOT}/backend"

"${VENV_PY}" -m pytest \
  tests \
  --junitxml="${PROJECT_ROOT}/artifacts/test-results/module1-junit.xml" \
  --cov=Connect \
  --cov=Integration \
  --cov=Text \
  --cov=Voice \
  --cov=Image \
  --cov-report=term-missing \
  "$@" | tee "${PROJECT_ROOT}/artifacts/test-results/pytest-output.txt"
```

---

## 附录 B：证据清单

所有验证都在**仓库之外**的临时目录（`%TEMP%\llmgal_probe`）完成；仓库 `git status --short` 全程为空。

| 编号 | 验证内容 | 命令要点 | 结果 |
|---|---|---|---|
| E1 | `python3.11` 是否存在 | 真实 Git Bash（5.2.26）执行 `command -v python3.11` | 空 → 不存在。coreutils（`dirname`/`tee`/`mkdir`）齐全 |
| E2 | 现存 `.venv-module1` 的布局与内容 | 读 `pyvenv.cfg`、列 `Scripts/`、`site-packages` | `home = E:\Anaconda\envs\vue-fastapi`、Python 3.11.13；只有 `Scripts/`（无 `bin/`）；site-packages 仅 pip 24.0 + setuptools 65.5.0 |
| E3 | 3.11 隔离环境跑全套用例 | `python -m venv`（3.11.9）+ `pip install -r backend/requirements-test.txt` + `pytest tests` | **32 passed, 2 xfailed in 1.6s**；覆盖率报告完整 |
| E4 | 3.12 隔离环境 | 同上，Python 3.12.8 | 收集阶段 `TypeError: ForwardRef._evaluate() missing 1 required keyword-only argument: 'recursive_guard'`，0 用例执行 |
| E5 | 3.13 隔离环境 | 同上，Python 3.13.14 | 与 E4 相同的报错 |
| E6 | 修正版脚本端到端 | 真实 Git Bash 执行附录 A 脚本（`LLMGAL_TEST_ROOT`/`LLMGAL_TEST_VENV` 指向临时目录） | 自动探测到 `py -3.11` → 建 venv → 装依赖 → **`32 passed, 2 xfailed in 3.16s`**，junit xml 生成 |
| E7 | `--asyncio-mode` 是否仍受支持 | 解包 `pytest_asyncio-1.0.0-py3-none-any.whl` 检索 `plugin.py` | 仍保留该选项，`pytest.ini` 的 `addopts` 有效 |
| E8 | `pydantic==1.10.7` 在 3.13 上能否单独导入 | `pip install --target` 后 `import pydantic` | **可以**导入。崩溃点在 fastapi 的 forward-ref 解析，不要被这一点误导 |
| E9 | 仓库是否被诊断过程污染 | `git status --short` / `--ignored` | 全程为空；`--ignored` 仅显示既有的 `.idea/`、`.venv-module1/`、`backend/.pytest_cache/`、`frontend/node_modules/` |
