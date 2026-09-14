# LLMGal 后端模块一 —— 缺陷定位与程序修正指南

> 定位依据：`scripts/run_module1_tests.sh` 实际运行输出（`artifacts/test-results/pytest-output.txt`、`module1-junit.xml`，32 passed / 2 xfailed / TOTAL 56%）、`docs/module1/LLMGal_backend_34_test_cases.md` 的预期契约，以及对 `backend/` 全量源码与 `frontend/src` 协议定义的静态核对。
>
> **本指南不包含任何源码改动。** 所有结论均标注了验证方式；未实测的推断已显式标记为"待确认"。

---

## 0. 结论摘要

**三个层次的缺陷，按修的优先级排列：**

1. **2 条 xfail 是真缺陷，不是设计妥协** —— TC-TTS-04（非法 Base64 写出零字节 mp3）、TC-EX-02（非数字索引在副作用之前就崩）。两者都能用一行修改解决，且修完必须同步删除 xfail 标记，否则 `strict=True` 会把 XPASS 判为失败。
2. **有 10 条"绿灯"用例断言的是缺陷行为** —— 它们 PASS 恰恰说明缺陷存在（TC-WS-05/06/08、TC-CFG-01/02/06、TC-EX-01、TC-RES-03、TC-ACK-03、TC-CON-01）。**改源码会让它们转红**，这是最容易被忽视的连带影响。
3. **覆盖率 56% 的缺口不是"少写测试"，而是死代码 + 被 mock 掩盖的架构问题** —— `Connect.py` 的 22–70 行和 `Voice.py` 的 64–189 行是已被 HTTP 路径取代的 WebSocket 二进制实现，全仓无调用方；`Text.py:54` 的 `delta.content != ""` 是真实运行必崩的 Bug，测试 mock 让它永远测不出来。

**另有一组工程卫生与安全问题不在测试覆盖范围内**：`backend/TestSubject.py` 是火山 ECS SDK 示例且含 `SyntaxError`；6 处 API 密钥硬编码入库；`pytest.ini` 缺 `testpaths`，任何人直接跑 `pytest` 会触发真实计费调用。

---

## 1. A 组：运行期失败（必须修，2 条）

### D1 · TC-TTS-04 非法 Base64 被静默接受，写出零字节 mp3

| 项 | 内容 |
|---|---|
| 位置 | `backend/Voice.py:191-204`（关键行：`195` 解码、`196-197` 写文件） |
| 现象 | `save_audio_from_base64("%%%%", "Wendy", "3")` 返回**非空**路径，并在 `voice/Wendy/Wendy_3_Stream.mp3` 留下 0 字节文件 |
| 根因 | `base64.b64decode(audio)` 默认 `validate=False`，会静默丢弃不在 Base64 字母表中的字符。实测：`b64decode('%%%%')` → `b''`，**不抛异常**；`b64decode('%%%%', validate=True)` → `binascii.Error: Only base64 data is allowed` |
| 影响 | 上游 `Voice_Generation_through_http` 把该路径当作成功产物返回；`Integration.Response_Collection` 不检查返回值；前端拿到 `status=success` 却无音频 |
| 修正方案 | ① 解码改 `base64.b64decode(audio, validate=True)`；② 解码后增加 `if not audio_data: return ""` 的空内容守卫；③ 保持"先解码、后 `open()`"的顺序不变（`os.makedirs` 在解码前只建目录不建文件，顺序本身是对的）；④ 建议顺手把返回值从相对路径改为绝对路径（见 D-arch-2） |
| 连带改动 | 删除 `backend/tests/test_service_and_state_cases.py:206` 的 `@pytest.mark.xfail(strict=True, reason="TC-TTS-04：当前实现会写入零字节音频")`。**必须删** —— `strict=True` 下用例通过会判为 XPASS→失败 |
| 验证 | 修完该用例应转为 PASS，且 `artifacts` 报告中 xfail 数从 2 降到 1 |

### D2 · TC-EX-02 非数字索引在副作用之前就崩，异常类型与文档不符

| 项 | 内容 |
|---|---|
| 位置 | `backend/Integration.py:119` 正则 `fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:(\d+)'` |
| 现象 | Records 中 `index:abc` → `re.findall` 返回 `[]` → `Integration.py:121` 的 `matches[0]` 抛 `IndexError`，LLM/TTS 一次都没调用 |
| 文档预期 | TC-EX-02 明确写："LLM 与 TTS 可在 `int(index)` 前已被调用；转换 `int('abc')` 时失败……该用例用于验证**部分副作用后失败**" |
| 根因 | 捕获组 `(\d+)` 过严，`abc` 直接导致整条记录不匹配 |
| 验证过的修法 | 改为 `index:([^\n]*)`。实测：对 `index:abc` 得 `('old-url','abc')`，对 `index:3` 得 `('old-url','3')`，正常路径不受影响；随后 `Integration.py:200` 的 `int(index)` 自然抛出 `ValueError`，与文档预期一致 |
| 连带改动 | 删除 `backend/tests/test_service_and_state_cases.py:384` 的 xfail 标记；断言 `calls == ["llm","tts"]` 与 `pytest.raises(ValueError)` 将同时成立 |
| 风险与边界 | 放宽后，"角色名能匹配但 index 是脏数据"的记录不再被静默跳过，而是走到 `int()` 才失败——这正是文档要的行为。TC-EX-01（角色记录完全缺失）仍是 `IndexError`，不受影响。现网 `frontend/src/assets/Records.txt` 四个角色的 index 均为纯数字，无迁移成本 |

---

## 2. B 组：当前 PASS 但断言的是缺陷行为（改源码必转红，共 10 条）

> 这一组是本次修正中最容易踩坑的地方：**用例是"契约快照"，不是"正确行为断言"**。改源码前必须先决定"改测试"还是"改实现"，两者要同批次提交。

| 用例 | 缺陷位置 | 当前行为（被断言为正确） | 建议修正方向 | 断言需同步改为 |
|---|---|---|---|---|
| TC-WS-05 | `Connect.py:227` | 缺 `type` → `KeyError` 冒泡到外层 → `SERVER_ERROR` | 改用 `message.get("type")` 显式判空，返回专用错误码 `MISSING_TYPE`，不依赖异常 | `[item["code"] for ...]` 期望值由 `["SERVER_ERROR"]` 改为新错误码 |
| TC-WS-06 | `Connect.py:233` | 缺 `payload` → `KeyError` → `SERVER_ERROR` | 同上，`MISSING_PAYLOAD` | 同上 |
| TC-WS-08 | `Connect.py:290-311` `send_error` | error 消息只有 `type/code/message/detail`，**没有 `message_id`/`status`/`payload`** | 按前端契约补齐：`frontend/src/utils/MessageType.ts:100-110` 的 `isServerMessage()` 要求三者在位；`type` 必须落在 `ServerMessageType.ERROR`（已是 `"error"`，OK）。建议结构 `{type:"error", message_id, status:"error", payload:{code,message,detail}}` | 该用例最后一行 `assert not frontend_required <= error.keys()` 需反转为 `assert frontend_required <= error.keys()` |
| TC-CFG-01 | `Connect.py:237-241` | `process_query` 抛 `KeyError` → 发 `PROCESS_ERROR` → **`except` 分支没有 `continue`** → 继续用未绑定的 `resp` 构造响应 → `NameError` → 外层 `SERVER_ERROR`，一次请求回两条错误 | 在 `send_error(...,"PROCESS_ERROR",...)` 后补 `continue`；并把 `textModel_config["modelText"]` 改为带默认值的显式校验，返回 `MISSING_CONFIG` 一类语义错误码 | 期望值 `["PROCESS_ERROR","SERVER_ERROR"]` → `["PROCESS_ERROR"]`（或新码） |
| TC-CFG-02 | 同上 | 同上（`realTimeRendering` 缺失） | 同上 | 同上 |
| TC-CFG-06 | 同上 | 未知模型透传给 LLM，LLM 拒绝后同样双错误 | 同上；如需模型白名单另开一项改造（当前无白名单是有意为之还是遗漏，需你确认） | 同上 |
| TC-EX-01 | `Integration.py:121` | `matches[0]` 裸索引 → `IndexError` | 显式判断空列表，抛业务异常（如 `RecordsEntryNotFound`），错误信息含 role 名 | `pytest.raises(IndexError)` → 新异常类型 |
| TC-RES-03 | `Integration.py:85-95` `updateLinks` | Records 文件缺失时写入阶段无恢复 → `FileNotFoundError` 冒泡 | ① 写入前确保父目录存在；② 角色块不存在时追加而非报错；③ 用临时文件 + `os.replace` 原子替换 | `with pytest.raises(FileNotFoundError)` 需移除，改为断言"文件被重建且含新记录" |
| TC-ACK-03 | `Connect.py:268-273` | ACK 等待窗口内到达的**下一条业务请求被 `receive_json()` 当作 ACK 消费并丢弃**，前端永远等不到第二条响应 | 读取 ACK 时先判类型：若 `data.get("type") == "client_query"`，应把它退回处理队列（或直接放弃带内 ACK 机制，改用前端已实现的 `message_id` 匹配 `pendingRequests`，见 `frontend/src/stores/ClientChat.ts:21/70`） | 断言 `[item["message_id"] for ...] == ["m1"]` → `["m1","m2"]` |
| TC-CON-01 | `Integration.py:117-203` 整体读改写 | 两请求都读到 `index=3`、都写 `Wendy_3_Stream.mp3`、Records 丢失更新 | 按代价递增：① 用文件锁（`msvcrt.locking` / `portalocker`）包裹 Records 的 read-modify-write；② 按会话分配槽位，不再共享 0–9；③ 迁出文本文件，改用 SQLite/Redis（requirements.txt 里已有 SQLAlchemy/redis 依赖，但代码没用） | 断言 `voice_slots == ["3","3"]` 与 `updates == [("Wendy","","4"),("Wendy","","4")]` 需改为串行化后的预期 |

> 补充（不单独占一条用例，但同属此类）：**TC-TTS-02** 断言了"TTS 失败后整体仍 `status=success`"。建议在 payload 中增加 `audioReady: bool`（或把 status 降级为 `partial`），让前端能区分"无音频"和"正常"；改后该用例的 `status` 断言需同步。

---

## 3. C 组：覆盖率缺口背后的死代码与真实 Bug

当前覆盖率：`Connect 73% / Integration 83% / Text 76% / Image 40% / Voice 31% / TOTAL 56%`。

### 3.1 死代码（建议删除，而非补测试）

| 位置 | 说明 |
|---|---|
| `Connect.py:16-32` `WebSocketManager`、`Connect.py:34` `ws_manager`、`Connect.py:36-70` `inner_websocket_operation` | 全仓 grep 只有定义处，**无任何调用方**。`websocket_chat` 不走它。属于"TTS 走 WebSocket 二进制协议"时期的实现，已被 `Voice.Voice_Generation_through_http` 取代 |
| `Connect.py:13` `from Voice import parse_response` | 仅为上述死代码服务，删后可一并移除 |
| `Voice.py:64-124` `test_submit`、`Voice.py:126-183` `parse_response`、`Voice.py:187-189` `Voice_Generation` | 同上，WebSocket 二进制 TTS 遗留，无任何调用方 |
| `Voice.py:36-61` `request_confirmation(voice, emo, text)` | 与 `Integration.py:38-82` 的 `request_confirmation(voice, emo)` **同名不同语义**：前者收整数音色编号 `0-3`，后者收 `"GirlFriend"` 这类类别字符串。是典型的重复实现陷阱，建议删除或重命名为私有函数 |

删完这些，`Voice.py` 与 `Connect.py` 的覆盖率会自然跃升，且不会再有人误以为"低覆盖是因为测试不够"。

### 3.2 真实 Bug（与覆盖率无关，静态核对发现）

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| D3 | `Text.py:54` `if delta.content != "":` | OpenAI 流式响应最后一个 chunk 的 `delta.content` 是 `None`，`None != ""` 为 `True` → `answer_content += None` → **`TypeError`**。真实调用必崩；测试 mock 固定返回字符串，永远测不到 | 改为 `if delta.content:` |
| D4 | `Image.py:83` `pattern_appearance = r'Appearance Details:\s*(.+?)(?=\0|$)'` | `\0` 是 NUL 字符，属于笔误（应为 `\n` 或直接用 `$`）。实测：对 `Subject Description: aaa\nAppearance Details: bbb\nccc`，appearance 捕获为 `bbb\nccc` —— **把换行之后的所有内容都吃了** | 改为 `r'Appearance Details:\s*(.+?)$'`（配合 `re.MULTILINE`）或 `r'Appearance Details:\s*(.+)'` |
| D5 | `Image.py:85-88` | `subject_description[0]` / `appearance_details[0]` 裸索引，文件为空或格式不符时 `IndexError` | 判断空列表后再索引，或返回带默认值的元组 |
| D6 | `Image.py:27-45` `save_image_from_url` | `requests.get` 无 `timeout`、无重试，异常只 `print` 后返回 `False`，调用方 `Image.py:133/193/209` 不检查返回值 | 加 `timeout`；让调用方感知失败 |
| D7 | `Voice.py:22` + `Voice.py:237` `reqid` | 模块级 `uuid.uuid4()` 只生成一次，所有请求复用同一 `reqid` | 改为每次请求生成（HTTP 分支里已有 `str(reqid)`，把 `uuid.uuid4()` 移入函数内） |
| D8 | `Integration.py:151` `except:` | 裸捕获会吞掉 `KeyboardInterrupt` / `SystemExit` | 改为 `except Exception:` |
| D9 | `Connect.py:175` `index = "8"` | 默认响应硬编码 index 为 `"8"`，语义不明，应是 `"0"` | 确认后修正或改为无默认 |

### 3.3 需要补测的生产路径

`Image.py` 只剩 40%，未覆盖的都是真实付费路径：`save_image_from_url`(29-45)、`create_role_image_prompt`(48-66)、`get_role_image_prompt`(70-88)、`original_image_generation`(92-135)、`byteedit_v2.0` 分支(195-211)、`__main__`(279-283)。

建议补测顺序：`get_role_image_prompt`（纯解析，零成本，且能顺带锁住 D4 的修复）→ `save_image_from_url`（mock `requests.get` 的成功/非 200/异常三态）→ `original_image_generation` / `emotional_bro`（mock `VisualService`，`test_service_and_state_cases.py` 里已有现成的 fake 可复用）。

---

## 4. D 组：架构级缺陷（mock 掩盖，测试全绿但生产会出问题）

| 编号 | 问题 | 依据 | 建议 |
|---|---|---|---|
| D-arch-1 | **同步阻塞事件循环**：`Connect.websocket_chat` 是 async，内部直接调用同步 `process_query`，其中串行执行 LLM 流式请求 + TTS HTTP(30s timeout) + 火山图片生成。单个请求会卡死整个 uvicorn 事件循环，其余连接全部无响应 | `Connect.py:238`、`Integration.py:135/158/174` | `await asyncio.to_thread(process_query, ...)` 或 `starlette.concurrency.run_in_threadpool`；长期应把 `Text.get_llm_response` 改成原生 async |
| D-arch-2 | **相对路径依赖 cwd**：`Voice.py:113/193`、`Image.py:48/72/108/159/220`、`Integration.py:86/89/117`、`Text.py:14` 全部用 `../frontend/src/assets/...`，只有 cwd 恰好是 `backend/` 才正确。换一种启动方式（`uvicorn backend.Connect:app`）就写到错误目录 | 全仓 grep | 定义绝对路径常量（如 `REPO_ROOT = Path(__file__).resolve().parents[1]`，`ASSETS = REPO_ROOT / "frontend/src/assets"`），或从配置/环境变量注入。**注意**：改后 `tests/conftest.py` 与两个测试文件里 `monkeypatch.chdir(tmp/"backend")` + `../frontend/...` 的假设需同步调整，否则 34 条用例会大面积转红 |
| D-arch-3 | **Records.txt 是无并发保护的文本状态**：`updateLinks` 用 `readlines()` + 行号偏移 `lines[i+1]`/`lines[i+2]` 改写，且 `Integration.py:91` 用 `if f"{roleName}:\n" in lines[i]` —— `in` 而非 `==`，角色名是另一个角色名的子串时会误命中 | `Integration.py:85-95` | 见 TC-CON-01 的修正方向；至少改用 `==` 精确匹配 + 原子写 |
| D-arch-4 | **`updateLinks` 会把已有 URL 清空**：静态模式下 `static_images` 返回 `""`，随后 `updateLinks(role, "", index)` 把 `Recent_Url:` 写成空。现网 `frontend/src/assets/Records.txt` 中 Wendy / Testificate / GirlProgrammer 的 `Recent_Url:` **已经是空**，与代码行为吻合，说明这个缺陷已经真实发生过 | `Integration.py:198/203` + `Records.txt` 实际内容 | `updatedUrl` 为空时跳过 URL 覆写，只更新 index |

---

## 5. E 组：项目结构与工程卫生

### E-1 死文件 / 污染文件（均已被 git 跟踪）

| 文件 | 问题 |
|---|---|
| `backend/TestSubject.py` | 火山云 ECS SDK 示例（创建云主机），与本项目无关；`from __future__ import print_function` 位于第 5 行 → **已验证 `SyntaxError: from __future__ imports must occur at the beginning of the file`**。任何全量 `pytest` 收集或 `compileall` 都会因此报错 |
| `backend/TestSubject2.py` | 情绪/音色枚举实验稿，与 `Image.py` / `Integration.py` 重复定义；且 `StandardBoyfriend.code = "zh_male_yangguangqingnian_..."` 与 `Integration.py:48` 的 `"zh_male_yourougongzi_..."` **不一致** |
| `backend/image_emotions.py`、`backend/tts_websocket_demo.py` | 一次性调试脚本，含硬编码 AK/SK |
| `backend/Create_New_Role.py` | 只有一行注释的空壳 |

### E-2 测试收集风险（当前靠脚本参数兜着）

`backend/pytest.ini` 只有 `asyncio_mode = auto` 与 `addopts = --asyncio-mode=auto`，**没有 `testpaths`**。仓库根目录下的 `backend/test_websocket.py` 会连接真实 `ws://localhost:8000/ws/chat` 并触发真实 LLM / TTS / 火山调用（无 mock，无 skip 标记）。

`scripts/run_module1_tests.sh` 显式传了 `tests` 参数所以当前安全；但只要有人直接执行 `pytest`（CI、IDE 侧边栏、手动），就会发起真实计费请求。

建议：在 `pytest.ini` 加 `testpaths = tests`；并把 `backend/test_websocket.py` 移入 `tests/integration/`、加 `@pytest.mark.integration` + 默认 `--ignore` 或 `addopts` 里 `-m "not integration"`。

### E-3 凭据硬编码入库（严重，建议优先处理）

| 位置 | 内容 |
|---|---|
| `Voice.py:17-18` | 火山 TTS `appid` / `token` |
| `Voice.py:116`、`Voice.py:213` | 同一个 token 明文重复出现两次 |
| `Text.py:38` | OpenAI `api_key`（`sk-...`）+ 中转 base_url |
| `Image.py:9-10`、`TestSubject2.py:8-9`、`image_emotions.py:4-5` | 火山 `ACCESS` / `SECRET`（SECRET 是 base64 明文，可直接解码） |

仓库已带 LICENSE 与 README，属可公开状态。建议：全部改为读环境变量或 `.env`（`requirements.txt` 里已有 `python-dotenv`），并把已泄漏的 key **作废轮换** —— 只删代码不轮换，git 历史里仍然留着。

### E-4 依赖管理

`backend/requirements.txt`（72 行）是 `pip freeze` 全量快照，含 Flask、SQLAlchemy、redis、mysqlclient、websocat、google、pptree 等与本项目无关的项；真正的运行最小集接近 `requirements-test.txt` 那 7 行。

更关键的副作用：`tests/conftest.py:17-39` 在 `openai` / `volcengine` 未安装时注入 stub，**意味着生产 SDK 从未被任何测试覆盖**。建议：① 拆出最小 `requirements.txt`，快照另存 `requirements-lock.txt`；② 给 conftest 的 stub 加显式开关（如只在 `LLMGAL_STUB_SDK=1` 时启用），避免将来 CI 装齐了 SDK 却仍在用 stub 跑出"虚假绿灯"。

### E-5 已入库的构建产物

- `backend/__pycache__/*.pyc` 共 7 个被 git 跟踪（含 `-pytest-8.4.1` 变体）→ `git rm --cached` + 加 `.gitignore`
- `backend/.idea/` 整个目录（9 个文件）被跟踪 → 同上

### E-6 跨端字段不一致（静态检查发现，前端未实跑，待你确认）

- `frontend/src/stores/ClientChat.ts:86-88` 与 `UseChatClient.ts:81` 用的是 **`imageMode_config`**；而类型定义 `MessageType.ts:40`、视图 `ChatView.vue:507`、后端 `Connect.py:138` 都是 **`imageModel_config`**。按代码路径，`UseChatClient.ts` → `LLMClient.sendQuery` 发出的 payload 会缺 `imageModel_config` → 后端 Pydantic 校验失败 → `VALIDATION_ERROR`。需确认前端实际走 Store 还是 ChatView 自建的链路。
- `ClientChat.ts:56` 把 `sendQuery` 的 `text` 声明为 `string`，而 `MessageType.ts:36` 定义为 `text: Message`，后端 `Text.get_llm_response`（`Text.py:35`）的 `full_prompt.append(prompt)` 期待的是 message dict。三处约定互不统一。

---

## 6. 修正顺序建议

每一阶段结束都应能独立跑通回归，避免一次性大改导致无法定位。

| 阶段 | 内容 | 涉及文件 | 预期结果 |
|---|---|---|---|
| **阶段 0** 工程卫生 | 删污染文件；`pytest.ini` 加 `testpaths`；清除已跟踪的 `.pyc` 与 `.idea`；凭据外置 + 轮换 | `backend/TestSubject*.py`、`image_emotions.py`、`tts_websocket_demo.py`、`pytest.ini`、`.gitignore`、各源码顶部 | 34 条用例结果不变；`pytest`（无参数）不再触碰真实服务 |
| **阶段 1** 修两个 xfail | D1、D2 + 删除两处 xfail 标记 | `Voice.py:195`、`Integration.py:119`、`tests/test_service_and_state_cases.py:206/384` | **34 passed, 0 xfailed** |
| **阶段 2** 契约型用例同步 | B 组 10 条：逐条改实现 + 逐条改断言 | `Connect.py:227/233/237-241/268-273/290-311`、`Integration.py:85-95/121`、两个测试文件 | 用例数仍为 34，全部 PASS；每条改动单独提交便于回滚 |
| **阶段 3** 死代码清理 + 补测 | 删 `Connect.py:16-70` 与 `Voice.py:64-189`；修 D3–D9；补 `Image.py` 生产路径测试 | `Connect.py`、`Voice.py`、`Image.py`、`Text.py`、`Integration.py`、新增测试 | 覆盖率 TOTAL 从 56% 提升；`Voice.py`/`Connect.py` 覆盖率应显著上升 |
| **阶段 4** 架构级改造 | D-arch-1 异步化、D-arch-2 绝对路径、D-arch-3/4 状态存储与并发 | `Connect.py`、`Integration.py`、`Image.py`、`Text.py`、`Voice.py` + 测试的路径假设 | 需要重新审视测试中的 `monkeypatch.chdir` 假设，改动面最大，建议单独一轮 |

---

## 7. 回归验证方法

```bash
# 已加固的脚本（自动建 venv、装依赖、转路径、生成产物）
"/c/Program Files/Git/bin/bash.exe" "F:/LLMGal/scripts/run_module1_tests.sh"
```

判定基线：

- `artifacts/test-results/pytest-output.txt` 末行：`34 passed, 0 xfailed`（阶段 1 之后）
- `artifacts/test-results/module1-junit.xml`：34 个 `<testcase>`，无 `<failure>` / `<error>`
- 覆盖率 TOTAL 只增不减

排查技巧：改完先跑 `pytest tests -q -rxX`（`-rxX` 会打印 xfail/xpass 的原因）。**重点看 XPASS** —— 本仓库的 xfail 都带 `strict=True`，用例一旦通过反而判失败，这是修 D1/D2 后最常见的"怎么还是红的"原因。

---

## 8. 缺陷速查表

| 编号 | 级别 | 位置 | 一句话 | 关联用例 |
|---|---|---|---|---|
| D1 | P0 | `Voice.py:195` | 非法 Base64 静默解码为空，写出 0 字节 mp3 | TC-TTS-04 (xfail) |
| D2 | P0 | `Integration.py:119` | index 正则 `(\d+)` 过严，异常早于副作用 | TC-EX-02 (xfail) |
| D3 | P0 | `Text.py:54` | `delta.content != ""` 对 `None` 为真 → `TypeError`，真实调用必崩 | 未被覆盖 |
| D-arch-1 | P0 | `Connect.py:238` | 同步阻塞事件循环，单请求拖垮全服务 | 被 mock 掩盖 |
| D-arch-4 | P0 | `Integration.py:198/203` | 静态模式下把已有 `Recent_Url` 清空 | 现网数据已受损 |
| E-3 | P0 | 6 处源码 | API 密钥硬编码入库且仓库公开 | — |
| TC-WS-08 | P0 | `Connect.py:290-311` | error 消息缺 `message_id`/`status`/`payload`，前端判为非法 | TC-WS-08 |
| TC-ACK-03 | P0 | `Connect.py:268-273` | 业务消息被当作 ACK 吞掉 | TC-ACK-03 |
| TC-CON-01 | P0 | `Integration.py:117-203` | 同角色并发无锁，资源互相覆盖 | TC-CON-01 |
| D4 | P1 | `Image.py:83` | `\0` 笔误导致 appearance 多吃后续全部文本 | 未被覆盖 |
| D5 | P1 | `Image.py:85-88` | 裸索引 `[0]`，空文件 IndexError | 未被覆盖 |
| D6 | P1 | `Image.py:27-45` | 下载无 timeout/重试，失败被吞 | 未被覆盖 |
| E-2 | P1 | `pytest.ini` | 无 `testpaths`，直接跑 pytest 会触发真实计费调用 | — |
| E-1 | P1 | `TestSubject.py` | 无关 SDK 示例且含 SyntaxError | — |
| D7 | P2 | `Voice.py:22` | reqid 全局复用于所有请求 | 未被覆盖 |
| D8 | P2 | `Integration.py:151` | 裸 `except:` | 未被覆盖 |
| D9 | P2 | `Connect.py:175` | 默认 index 硬编码 `"8"` | — |
| E-6 | P1（待确认） | `ClientChat.ts:86-88` | `imageMode_config` 与后端 `imageModel_config` 不一致 | 端到端未验证 |
