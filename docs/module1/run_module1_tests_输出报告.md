# `scripts/run_module1_tests.sh` 策略 A 执行报告

> 执行日期：2026-09-12
> 执行环境：Windows 11 / Git Bash 5.2.26 / 仓库 `F:\LLMGal`
> 执行范围：加固脚本 → 本地运行 → 检查结果 → 出报告
> **未执行任何 `git commit` / `git push`，所有改动留在工作区待你审核。**

---

## 一、执行概要

| 项 | 结果 |
|---|---|
| 脚本加固 | 完成，`scripts/run_module1_tests.sh`（+94 / −11 行） |
| 首次运行 | 触发一个新暴露的坑（MSYS 路径），失败，已修复 |
| 修复后运行 | **成功**，`32 passed, 2 xfailed`，耗时 3.55s |
| 二次运行（幂等验证） | 成功，跳过依赖安装，耗时 2.45s |
| 用例总数 | 34（与 `LLMGal_backend_34_test_cases.md` 的 34 条一一对应） |
| 失败 / 错误 | 0 / 0 |
| 产物 | `artifacts/test-results/module1-junit.xml`、`pytest-output.txt` |
| GitHub 提交 | **无** |

一句话结论：策略 A 落地后，脚本在 Windows + Git Bash 上可以开箱即用地跑通全套模块一测试，且重复执行时幂等。

---

## 二、脚本改动说明

改动集中在一处文件，四个新增能力 + 一个路径转换修复。

### 1. 解释器探测链（替换原来硬编码的 `python3.11`）

```
LLMGAL_TEST_PYTHON → python3.11 → py -3.11 → 校验过版本的 python3
```

用 bash 数组 `BASE_PY` 承载，因此 `py -3.11` 这种「命令 + 参数」两段式也能正确传递（原脚本把它当单个文件名，是天然跑不通的）。

### 2. venv 解释器双布局探测

```bash
venv_python() {
  [[ -x "${VENV_DIR}/bin/python" ]]      && echo "${VENV_DIR}/bin/python"        # POSIX
  [[ -x "${VENV_DIR}/Scripts/python.exe" ]] && echo "${VENV_DIR}/Scripts/python.exe"  # Windows
}
```

这是原脚本在 Windows 上的致命假设（只认 `bin/`）。

### 3. 3.11 版本断言

任何解释器被选中后立刻执行：

```bash
"$@" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)'
```

把「误用 3.12 / 3.13」拦在一条清晰的报错里，而不是让它以几十行 pydantic 栈回溯的形式炸出来。

### 4. 依赖自愈

```bash
venv_ready() { "${py}" -c 'import pytest, fastapi, pydantic, requests, websockets' >/dev/null 2>&1; }
```

venv 可能存在但依赖不全（本仓库的 `.venv-module1` 正是这种情况：有 `Scripts/python.exe`，但 site-packages 里只有 pip + setuptools）。原脚本只看解释器是否存在，会直接跳到 pytest 然后 `ModuleNotFoundError`。现在会先探测，缺了才装。

### 5. 路径形式转换（运行中暴露，见下节）

```bash
to_native() { command -v cygpath >/dev/null 2>&1 && cygpath -m "$1" || printf '%s\n' "$1"; }
```

凡是要传给**原生 Windows 解释器**的路径（`-r <requirements>`、`--junitxml`、venv 创建目标），统一转成 `F:/...`；bash 自己用的路径（`mkdir`、`cd`、`tee`）仍用 MSYS 的 `/f/...`。

---

## 三、执行过程

### 第一次运行：暴露第三层坑

加固后的脚本第一次跑，卡在依赖安装：

```
[环境] /f/LLMGal/.venv-module1 缺少测试依赖，开始安装 backend/requirements-test.txt
Successfully installed pip-26.2.1
ERROR: Could not open requirements file: [Errno 2] No such file or directory:
       '/f/LLMGal/backend/requirements-test.txt'
```

**原因**：`/f/LLMGal/...` 是 MSYS/Git Bash 的虚拟路径，只有 MSYS 自己的程序认。venv 里的 `python.exe` 是**原生 Windows 程序**，`/f/LLMGal` 在它眼里就是根目录下一个不存在的目录。

**这层坑在上一轮审计里没暴露**，因为原脚本更早就死在 `bin/python` 上，根本走不到这一步。它说明 Windows Git Bash 跑 POSIX 脚本有三层不兼容，而不只是两层：

| 层 | 表现 | 是否已修 |
|---|---|---|
| 解释器命名 | `python3.11` 不存在，Windows 用 `py -3.11` | 已修 |
| venv 布局 | `bin/` vs `Scripts/` | 已修 |
| 路径形式 | MSYS `/f/...` vs 原生 `F:/...` | 已修（本次新发现） |

### 第二次运行：成功

修复后重跑，脚本自动完成：

1. 探测到 `.venv-module1/Scripts/python.exe`（Python 3.11.13，Anaconda 基座）
2. 版本断言通过
3. 依赖自愈判定为「缺依赖」→ pip 安装 20 个包（fastapi 0.95.1 / pydantic 1.10.7 / pytest 8.4.1 / pytest-asyncio 1.0.0 / pytest-cov 6.2.1 / requests 2.32.4 / websockets 11.0.2 及传递依赖）
4. 进入 `backend/`，跑 `pytest tests`
5. 结果：`32 passed, 2 xfailed in 3.55s`

### 第三次运行：幂等验证

再次执行，输出中**完全没有 pip 相关行**，直接进入测试，`32 passed, 2 xfailed in 2.45s`。证明依赖自愈判定生效、不会每次重装。

---

## 四、运行结果

### 4.1 会话信息

```
platform win32 -- Python 3.11.13, pytest-8.4.1, pluggy-1.6.0
rootdir: F:\LLMGal\backend
configfile: pytest.ini
plugins: anyio-4.15.1, asyncio-1.0.0, cov-6.2.1
asyncio: mode=Mode.AUTO
collected 34 items
```

junit 汇总：`tests=34, failures=0, errors=0, skipped=2, time=3.528`。

### 4.2 用例明细（34 条）

**服务编排与状态类** —— `backend/tests/test_service_and_state_cases.py`（20 条）

| 用例 | 结果 | 耗时 |
|---|---|---|
| TC-CFG-04 四类有效音色映射 | PASS | 0.033s |
| TC-CFG-05 未知音色默认回退 | PASS | 0.002s |
| TC-LLM-01 角色 Prompt 追加情绪指令 | PASS | 0.029s |
| TC-LLM-03 无括号时情绪默认值 | PASS | 0.013s |
| TC-LLM-04 仅一个括号 | PASS | 0.010s |
| TC-LLM-05 两个以上括号 | PASS | 0.012s |
| TC-TTS-01 TTS 成功保存 Base64 音频 | PASS | 0.016s |
| TC-TTS-02 TTS 超时后流程继续 | PASS | 0.013s |
| TC-TTS-04 非法 Base64 | **XFAIL** | 0.016s |
| TC-TTS-05 TTS 返回非 JSON | PASS | 0.011s |
| TC-IMG-01 静态图恰好 7 张 | PASS | 0.018s |
| TC-IMG-02 缺 1 张触发重生成 | PASS | 0.018s |
| TC-IMG-03 实时图生图成功 | PASS | 0.017s |
| TC-IMG-04 实时异常回退文生图 | PASS | 0.014s |
| TC-RES-01 索引 8 → 9 | PASS | 0.012s |
| TC-RES-02 索引 9 回绕到 0 | PASS | 0.013s |
| TC-RES-03 Records 缺失回退 | PASS | 0.008s |
| TC-EX-01 角色记录缺失 | PASS | 0.010s |
| TC-EX-02 索引非数字 | **XFAIL** | 0.012s |
| TC-CON-01 同角色并发状态覆盖 | PASS | 0.028s |

**WebSocket 协议类** —— `backend/tests/test_websocket_cases.py`（14 条）

| 用例 | 结果 | 耗时 |
|---|---|---|
| TC-WS-01 合法请求完整主流程 | PASS | 0.028s |
| TC-WS-02 非法 JSON | PASS | 0.005s |
| TC-WS-04 非 client_query 类型 | PASS | 0.005s |
| TC-WS-05 缺少顶层 type | PASS | 0.008s |
| TC-WS-06 缺少 payload | PASS | 0.006s |
| TC-WS-07 payload 缺必填字段 | PASS | 0.006s |
| TC-WS-08 错误响应协议兼容性 | PASS | 0.005s |
| TC-CFG-01 缺 modelText | PASS | 0.007s |
| TC-CFG-02 缺 realTimeRendering | PASS | 0.007s |
| TC-CFG-06 未知文本模型 | PASS | 0.007s |
| TC-EX-03 客户端断开隔离性 | PASS | 0.008s |
| TC-ACK-01 正确 ACK | PASS | 0.006s |
| TC-ACK-02 ACK 超时 | PASS | 0.006s |
| TC-ACK-03 未 ACK 时下条消息被误当 ACK | PASS | 0.008s |

用例耗时合计 0.402s，会话总耗时 3.528s（其余为导入与 fixture 开销）。

### 4.3 两个 XFAIL 说明

设计如此，不是失败，用来登记「文档预期」与「当前实现」的不一致：

| 用例 | 标记原因 |
|---|---|
| TC-TTS-04 | 当前实现会写入零字节音频（`save_audio_from_base64` 在解码失败时已写文件再返回） |
| TC-EX-02 | Records 索引的正则 `index:(\d+)` 先排除了非数字，走不到 `int('abc')` 那一步 |

两者都是**被测代码的行为观察结论**，不是测试写错。要消掉它们得先改 `backend/` 里的实现，属于另一个议题。

### 4.4 覆盖率

```
Name             Stmts   Miss  Cover   Missing
----------------------------------------------
Connect.py         138     37    73%   22-26, 30-32, 40-70, 210, 264-267, 282, 310-311, 314-315
Image.py           115     69    40%   29-45, 48-66, 70-88, 92-135, 195-211, 279-283
Integration.py     109     18    83%   67-68, 70-71, 75-80, 129-132, 151-154
Text.py             34      8    76%   18-21, 48-49, 61-62
Voice.py           160    111    31%   37-61, 65-124, 127-183, 188-189, 202-204, 257-258, 264-265, 270
----------------------------------------------
TOTAL              556    243    56%
```

未覆盖部分集中在三块，都是合理的缺口而非问题：

- **Voice.py 31%**：生产路径走 `Voice_Generation_through_http`（HTTP），而 `test_submit` / `parse_response` 那套 WebSocket 二进制协议实现（37–183 行）是历史遗留、当前没有调用方，单测也没覆盖。
- **Image.py 40%**：`original_image_generation` / `emotional_bro` 里对 `VisualService` 的调用被 conftest 的 stub 顶掉，只有分支逻辑被走到。
- **Connect.py 73%**：22–70 行是内部 WebSocket 管理器（`WebSocketManager` / `inner_websocket_operation`），同样属于被 HTTP 路径取代的遗留代码；310–315 行是 `uvicorn.run` 启动段。

---

## 五、产物清单

| 路径 | 大小 | 说明 |
|---|---|---|
| `artifacts/test-results/module1-junit.xml` | 4798 B | JUnit XML，34 条用例逐条记录，供 CI 消费 |
| `artifacts/test-results/pytest-output.txt` | 1471 B | 终端输出副本（含覆盖率表） |
| `backend/.coverage` | — | coverage 数据文件，脚本默认落在 `backend/` |

以上三项均已被 `.gitignore` 覆盖（`.venv-module1/`、`artifacts/test-results/`、`.coverage`），不会进仓库。

---

## 六、仓库状态（**未提交**）

```
$ git status --short
 M scripts/run_module1_tests.sh
?? .workbuddy/
?? docs/module1/run_module1_tests_环境适配指南.md
?? docs/module1/run_module1_tests_输出报告.md      ← 本文件

$ git diff --stat
 scripts/run_module1_tests.sh | 105 ++++++++++++++++++++++++++++++++++++++-----
 1 file changed, 94 insertions(+), 11 deletions(-)
```

当前 HEAD：`0c401fe Update Something Useless`，分支上无新提交。

**关于 `.workbuddy/`**：这是 AI 助手的工程记忆目录（记录本次审计结论与环境坑），不是项目产物。建议提交前把它加进 `.gitignore`，或者直接不纳入这次提交。

**已确认未被污染**：仓库里 7 个被 git 跟踪的 `backend/__pycache__/*.pyc` 全部未被改写——`PYTHONDONTWRITEBYTECODE=1` 生效，`git status` 中没有它们。

---

## 七、遗留事项与建议

1. **`.workbuddy/` 处置**：建议加 `.gitignore`，或不纳入提交。需要我改 `.gitignore` 就说一声。
2. **`backend/.coverage`**：脚本默认把 coverage 数据文件落在 `backend/`。已被忽略，但如果不想在工作目录留文件，可以给脚本加 `COVERAGE_FILE` 指向 `artifacts/`。
3. **venv 基座**：`.venv-module1` 用的还是 Anaconda 的 3.11.13（上次遗留）。能跑通，但如果想要一个干净、与 Anaconda 解耦的环境，可以删掉它让脚本用 `py -3.11`（python.org 3.11.9）重建。
4. **两个 XFAIL**：要消掉需要改 `backend/` 实现（`Voice.save_audio_from_base64` 的写入时机、`Integration.Response_Collection` 的索引正则），属于独立于本次环境修复的议题。
5. **覆盖率缺口**：`Voice.py` 的 WebSocket 二进制协议实现（37–183 行）与 `Connect.py` 的内部连接管理器（22–70 行）当前没有任何调用方，考虑是删是留。
6. **CI 侧**：若在 GitHub Actions 上跑，加 `python-version: 3.11` 即可，脚本在 Linux 上走 `python3.11` 分支、用 `bin/` 布局，原样可用。
