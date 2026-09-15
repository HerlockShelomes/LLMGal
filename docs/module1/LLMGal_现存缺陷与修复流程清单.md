# LLMGal 现存缺陷核对与修复流程清单

| 项目名称 | LLMGal（Vue3 + FastAPI 对话式 Galgame） |
|---|---|
| 文档版本 | V2.0 |
| 编制日期 | 2026-09-13 |
| 核对基线 | `git HEAD = 4e9806f`（"First Stage Fix"，2026-09-13 15:17） |
| 上游依据 | `LLMGal_前后端现存缺陷清单报告.md`（V1.0，基线 `0c401fe`）、`LLMGal_测试缺陷报告书.docx`（V1.0，基线 `0c401fe`） |
| 本轮方法 | 逐文件重读 `backend/*.py`、`frontend/src/**`、`backend/tests/**`；`git show 4e9806f` 比对实际改动；与两份文档逐条对齐后再判定 |
| 核心结论 | 文档登记的 **11 条**已修 **8 条**；V1.0 清单的 **53 条**中约 **20 条**已收敛；**仍有 30+ 条未修**；本轮另**新增 12 条**两份文档均未登记的缺陷 |

---

## 零、先读这一节（三个必须先知道的事实）

**事实一：两份文档已过期，其基线 `0c401fe` 不是当前代码。**
`4e9806f "First Stage Fix"` 改了 7 个文件（`Connect.py` +72 行、`Integration.py` +123 行、`Voice.py` +11 行、两个测试文件、`ChatView.vue` +12 行）。因此**直接照 V1.0 清单动手会出现"修一个已经修好的东西"和"被测试红灯误导"两类浪费**。本清单以当前代码为准。

**事实二：测出"绿灯"的用例里，仍有 6 条在断言缺陷行为。**
改动源码后这些用例会变红，极易被误判为回归。精确名单见第 4 章，逐条给了行号。

**事实三：项目目前不存在任何多轮对话上下文。**
`ChatView.vue:513`（WebSocket 主链路）只发送 `slice(-2)[0]` 这一条消息；`Text.py:35` 把它追加到只有一条角色设定的数组里。也就是说，**"接入正式 AI 对话"这件事，需要先补一个上下文层，而不是只换模型**。详见第 5 章。

---

## 一、修复收敛情况（对齐 `LLMGal_测试缺陷报告书.docx` 的 11 条）

### 1.1 已修复 —— 8 条

| 缺陷书编号 | V1.0 编号 | 当前落点（修复后） | 关键证据 |
|---|---|---|---|
| 001 非法 Base64 静默写 0 字节 mp3 | D22 | `Voice.py:191-213` `save_audio_from_base64` | 先 `"".join(audio.split())` 剥离空白 → `b64decode(..., validate=True)` → `if not audio_data: return ""` |
| 002 非数字 index 异常类型/位置错误 | D13 | `Integration.py:176` | 捕获组 `(\d+)` → `([^\n]*)`；`int()` 仍在 `:273`，ValueError 落点正确 |
| 003 error 响应不符合前端契约 | D05 | `Connect.py:318-351` `send_error` | 已带 `message_id` / `status` / `payload`；`ChatView.vue:458-465` 另加 `invalid_message` 兜底监听 |
| 004 PROCESS_ERROR 后未终止流程 | D08 | `Connect.py:274` | `except` 分支补 `continue`，不再用未绑定的 `resp` 二次报错 |
| 005 ACK 窗口吞掉业务请求 | D07 | `Connect.py:218-239`、`304` | 改为 `pending_ack_id` 登记，且要求 `message.get('type') != 'client_query'` |
| 006 同角色并发无锁 | D10 | `Integration.py:16-23` `_lock_for`、`:44-55` `_advance_index_only`、`:170-205` | 按角色名分片 `threading.Lock` + 锁内原子占位 |
| 007 Records 缺失时写回失败 | D13/D12 部分 | `Integration.py:139-149` | `updateLinks` 的 `for/else` 分支补最小记录 |
| 008 角色记录缺失抛 IndexError | D13 | `Integration.py:178-186` | `matches` 判空后降级为静态模式，不再 `matches[0]` |

### 1.2 仍未修复 —— 3 条

| 缺陷书编号 | V1.0 编号 | 现状证据 | 影响 |
|---|---|---|---|
| **009 TTS 失败仍返回 status=success** | D11 | `Integration.py:231` 调用 `Voice_Generation_through_http(...)` 但**丢弃返回值**；`Connect.py:280` 恒写 `"status": "success"` | 用户看到完整文字却听不到语音，且无法区分"网络故障"与"设计如此" |
| **010 覆盖率 56% < 70%** | D13/工程 | `backend/.coverage` 显示升至 57%，`Voice.py` 33%、`Image.py` 40% | 音频二进制协议解析、图片下载/生成路径几乎零覆盖 → 上线后才会暴露 |
| **011 pytest.ini 缺 testpaths** | D17 | `backend/pytest.ini` 仍只有 3 行（`asyncio_mode` + `addopts`） | 任何人在 IDE 点一次 pytest 就收集 `test_websocket.py`，**触发真实 LLM/TTS/图片计费** |

---

## 二、仍未修复的缺陷全量清单

### 2.1 后端（按当前代码逐条核验）

| # | 等级 | 位置 | 缺陷 | 现状 |
|---|---|---|---|---|
| B01 | **P0** | `Text.py:38`、`Voice.py:17-18`/`116`/`222`、`Image.py:9-10`、`image_emotions.py:4-5` | 第三方中转站 Key（`sk-Tk2R...`）、火山 AK/SK、TTS appid/token 共 **6 处明文入库** | 未修 |
| B02 | **P0** | `Connect.py:212`、`:355` | `/ws/chat` 无握手鉴权；`uvicorn.run(host="0.0.0.0")` 全网卡监听 | 未修 |
| B03 | **P0** | `Connect.py:263` | `process_query` 是同步函数，内部串联同步 LLM 流 + `requests.post(timeout=30)` + 火山 SDK 同步调用，却在 `async def websocket_chat` 中直接执行 | 未修（**多用户可用的头号阻塞项**） |
| B04 | P1 | `Text.py:54` | `if delta.content != "":` —— 推理模型末个 chunk 的 `content` 为 `None`，`None != ""` 为真 → `answer_content += None` 抛 `TypeError` | 未修 |
| B05 | P1 | `Text.py:35` | `full_prompt.append(prompt)` 要求 `{role, content}` 字典；两条前端链路分别传对象/字符串 | 未修 |
| B06 | P1 | `Image.py:108`/`159` vs `:227-235` | 同一角色两套命名：`{role}_{数字}.jpg`（实时）与 `{role}_{情绪名}.jpg`（静态），互不同步 | 未修 |
| B07 | P1 | `Image.py:251` + `Integration.py:271`/`276` | 静态资源齐全时 `static_images` 返回 `""`，`updateLinks` 无条件写回 → **清空 `Recent_Url`，下次实时渲染退化到付费文生图** | 未修 |
| B08 | P1 | `Integration.py:273-275` | `int(index)` 位于 LLM / TTS / 图片生成**之后**，脏数据等于"钱花完才失败"，无回滚 | 保留（与 002 修复配套，但需补回滚） |
| B09 | P1 | `Integration.py:210-227` | 情绪提取 `r'\((.*?)\)'` 抓**所有**括号；映射表只认中文情绪词；`except:` 为裸捕获 | 未修 |
| B10 | P2 | `Integration.py:132-149` | `updateLinks` 在角色锁**之外**执行，且用 `f"{roleName}:\n" in lines[i]` 子串匹配 | 未修（→ 见 N01、N09） |
| B11 | P2 | `Voice.py:164-174` | `parse_response` 遇服务端错误帧（`0xf`）只打印日志后 `return True`，上层视为正常结束 | 未修 |
| B12 | P2 | `Voice.py:22`、`:246` | `reqid = uuid.uuid4()` 为模块级全局，HTTP 路径永远复用同一 `reqid`，而 `use_cache=True` | 未修 |
| B13 | P2 | `Image.py:27-45`、`:34` | `requests.get(url, stream=True)` 无 `timeout`；异常只 `print` 后 `return False`，调用方不检查 | 未修 |
| B14 | P2 | `Image.py:83-88` | `(?=\0\|$)` 中 `\0` 是 **NUL 字符笔误**（应为 `\n`）→ 吃掉 appearance 之后全部内容；且 `[0]` 裸索引无判空 | 未修 |
| B15 | P2 | `Image.py:132`/`191`/`207` | 直接取 `resp['data']['image_urls'][0]`，未校验响应结构 | 未修 |
| B16 | P2 | `Connect.py:242` | `message['type']` 下标访问；`except ValueError` 接不住 `KeyError` → 冒泡成 `SERVER_ERROR` | 未修 |
| B17 | P2 | `Connect.py:197`、`:175` | `tokens_used = len(response)` 用字符数冒充 token；`ServerResponse` 初值 `index = "8"` 为魔法数 | 未修 |
| B18 | P2 | 13 处 | `../frontend/src/assets/...` 相对路径依赖启动时 cwd（`Text.py:14`、`Voice.py:113`/`203`、`Image.py:48`/`72`/`108`/`159`/`220`、`Integration.py:12`/`37`/`172`） | 未修 |
| B19 | P3 | `Voice.py:36-61`、`:115` | `Voice.request_confirmation` 与 `Integration.request_confirmation` 同名不同语义且全项目零调用；`open()` 在 `websockets.connect` 之前、异常路径无 `finally` | 未修 |
| B20 | P3 | `Connect.py:314-316` | `finally: await websocket.close()` 被注释掉 | 未修 |
| B21 | P3 | `TestSubject.py` | `from volcenginesdktransitrouter import ...` 在 `from __future__ import ...` 之前 → `SyntaxError` | 未修 |
| B22 | P3 | `requirements.txt` | `websocat` 是 CLI 非可导入包；`Flask`/`mysqlclient`/`PyMySQL`/`redis`/`redis-om`/`SQLAlchemy`/`loguru` 零 import；缺 `volcenginesdk*`；`pytest` 混入生产依赖 | 未修 |
| B23 | P3 | `image_emotions.py` | 一次性调试脚本，硬编码已过期签名 URL，与 `Image.py` 重复定义 AK/SK | 未修 |
| B24 | P3 | `backend/__pycache__/*.pyc`（7 个）、`backend/.idea/`（9 个） | 构建产物与 IDE 配置入库 | 未修 |

### 2.2 前端（本轮逐文件核验，**26 条全部仍在**）

`4e9806f` 只给 `ChatView.vue` 加了 12 行 `invalid_message` 监听，**没有修复任何一条前端缺陷**。

| # | 等级 | 位置 | 缺陷 |
|---|---|---|---|
| F01 | **P0** | `utils/markdown.ts:9` + `ChatMessage.vue:167`、`SearchBar.vue:207` | MarkdownIt 开启 `html: true` 且无消毒，经 `v-html` 注入 → **XSS** |
| F02 | P1 | `utils/markdown.ts:22-24` | `${lang}` 未转义直接拼进 `class` → 第二个注入点 |
| F03 | P1 | `utils/markdown.ts:70` | `INLINE_MATH_RULES` 的 `/\[([^\]]+)\]/` 注册在 `before('escape')`，抢在 `link`/`image` 之前 → **所有 Markdown 链接与图片渲染失败** |
| F04 | P1 | `utils/messageHandler.ts:111` | `decoder.decode(value)` 未带 `{stream: true}` → 中文跨 chunk 截断成替换字符；被切断的 JSON 行仅 `console.error` 后丢弃 |
| F05 | P1 | `stores/ClientChat.ts:86`、`UseChatClient.ts:81` | 字段名 `imageMode_config`（应为 `imageModel_config`）→ Pydantic 必填缺失 |
| F06 | P1 | `views/ChatView.vue:415` | error 分支执行 `updateLastMessage(data.status, '')`，把 `"error"` 当正文写入气泡。**D05 修复后此分支已可达** |
| F07 | P1 | `ChatView.vue:652` vs `:330` | 首次发送走 WebSocket（含音频/表情联动），"重新生成"走 HTTP（无音频无表情） |
| F08 | P1 | `ChatView.vue:342-349` | `handleStop` 只调 `chatApi.abortRequest()`（HTTP），而实际通道是 WebSocket → **点"停止"后端仍继续执行并计费** |
| F09 | P2 | `utils/WebSocketManager.ts:123` | `off()` 内每次新建 wrapper，`Set.delete` 比较新引用 → **永远删不掉**，历史回调全部存活 |
| F10 | P2 | `components/SearchBar.vue:112` | setup 顶层给 `document.documentElement` 注册 click 监听，`onUnmounted` 只清理 keydown |
| F11 | P2 | `stores/chat.ts:61`/`106`、`ChatView.vue:297`/`308`/`616` | `id: Date.now()` 毫秒级取 ID 必然冲突；叠加 `splice(index, 2)` 的"成对删除"假设会连删无关消息 |
| F12 | P2 | `ChatView.vue:322` → `:324` | `handleRegenerate` 先 `splice(index-1, 2)` 再判 `isLoading` → 提前返回时消息已删且未重发，**内容丢失** |
| F13 | P2 | `components/ChatInput.vue:86`/`207` | 模板里 `URL.createObjectURL(file)`，每次重渲染生成新 Blob URL，全项目无 `revokeObjectURL` |
| F14 | P2 | `stores/chat.ts:194-197`、`settings.ts:154-159` | `persist` 把含 base64 图片的整个 `conversations` 写进 localStorage（5 MB 上限）；`apiKey` 明文落盘 |
| F15 | P2 | `stores/ClientChat.ts:186` → `:198` | `cancelRequest` 先 `delete` 再 `reject(new Error('请求已被用户取消'))`，把用户主动取消当异常抛 |
| F16 | P2 | `stores/UseChatClient.ts:124` vs `:105`/`:125` | `handleError(error, msg)` 调用处只传一参 → `msg` 恒 `undefined`，`error.value = undefined`，错误提示永不显示 |
| F17 | P2 | `settings.ts:20`/`24`、`ChatInput.vue:43`、`ChatView.vue:43`、`SettingsPanel.vue:352`/`381` | `new URL('/src/assets/...', import.meta.url)` 以 `/` 开头是 public 语义 → **`npm run build` 产物中所有角色图片/语音/文档 404** |
| F18 | P2 | `components/ChatInput.vue:229` | `@keydown.enter.exact.prevent` 未判断 `isComposing` → 中文输入法选词时按回车误发送半截内容 |
| F19 | P2 | `ChatView.vue:369`、`SettingsPanel.vue:397` | `audio.value.play()` 无 `catch` → 自动播放被拦截时抛未捕获 Promise 异常，无降级提示 |
| F20 | P2 | `ChatView.vue:604-609`、`:437` | `onBeforeUnmount` 被注释（卸载不断开连接），同时 `disconnected` 回调又主动 `reconnect()` → **双重重连** |
| F21 | P2 | `utils/WebSocketManager.ts:147` | `if (typeof data !== 'undefined')` 才回调 → 合法但不带 payload 的事件被静默丢弃 |
| F22 | P2 | `ChatView.vue:495` | `currentChatMessages.value.slice(-2)[0].content.trim()` 无判空 |
| F23 | P2 | `utils/MessageType.ts:105-109` | `isServerMessage` 未校验 `status`，与类型声明不一致；函数名 `isClientMessgage` 拼写错误 |
| F24 | P3 | `ChatView.vue:584-602`、`:661-664` | `runTests` 调试按钮与 `.debug-panel` 保留在模板中，可伪造 `assistant_response` 注入 store |
| F25 | P3 | `components/SideBar.vue:94`、`:93` + `:65-67` | 模板 `ref="editInputRef"` 未声明；Esc 取消重命名后 `@blur` 仍触发 `saveRename` |
| F26 | P3 | `ChatView.vue:480-481` + `WebSocketManager.ts:46` | 先 `await connect()` 再注册监听，而 `connect` 在 resolve 前已 `emit('connected')` → 该事件永久丢失 |
| F27 | P3 | `components/ChatInput.vue:224`、`SettingsPanel.vue:640` | `v-if="!getImageUrl(...)"` 恒为假 → 占位提示永不显示 |
| F28 | P3 | `stores/ClientChat.ts:204-207`、`UseChatClient.ts`/`ClientChat.ts` 全链路 | `retryQueue` 恒为空；`useChatClient`/`LLMClient` 整条链路全项目零引用（死代码，且与 `ChatView` 实际实现重复） |
| F29 | P3 | `utils/WebSocketManager.ts:45`/`:69`/`:158` | `startHeartbeat` 从未被调用（注释掉），心跳机制整体失效 |
| F30 | P3 | `src/_tests_/example.test.ts` | 前端唯一测试只断言 `expect(1+1).toBe(2)`；约 4600 行代码零测试保护 |

---

## 三、本轮新增缺陷（两份文档均未登记）

这 12 条是本次重读代码新发现的，多数是"上一轮修复引入或放大"的，**修复时必须与第 2 章一起排期**。

| 编号 | 等级 | 位置 | 缺陷描述 | 为什么会发生 / 影响 |
|---|---|---|---|---|
| **N01** | **P1** | `Integration.py:170-205` vs `:276` | **槽位推进已加锁，但最终写回 `updateLinks` 仍在锁外。** A 读 3→推进到 4，B 读 4→推进到 5；若 B 的 `updateLinks` 先落（写 `index:5`）、A 的后落（写 `index:4`），则 Records 的 index **回退为 4** | 006 号缺陷只解决了"读到同一个 index"，没解决"写回覆盖"。下一个请求会复用 B 已占用的槽位 4，覆盖 `{role}_4.jpg`；同时 `Recent_Url` 变成 A 的旧图，破坏图生图的风格参考链，角色形象漂移。**建议：把 `updateLinks` 纳入同一把角色锁，或改为"index 只由 `_advance_index_only` 独占推进、`updateLinks` 只写 URL"** |
| **N02** | P1 | `Text.py:34` | 角色设定用 `{"role": "assistant", "content": role_pro}` 承载，语义应为 `system` | 模型会把"你是 Wendy，性格……"当成**自己已经说过的话**，人格约束力显著下降；任何上下文压缩策略也会把这段当成对话历史处理。同时 `tests:104` 正在断言这个错误行为 |
| **N03** | P1 | `Text.py:14-21` | 角色提示词文件不存在时只 `print` 后返回 `""`，仍继续发起请求 | 角色扮演**完全失效但零错误信号**，用户看到的是一个没有性格的通用助手，日志里也看不出问题 |
| **N04** | **P1** | `Integration.py:231` | TTS 的输入是 LLM 的**原始完整回复**（含情绪括号），未剔除标签 | 用户会**亲耳听到**"（高兴）（因为受到朋友的邀请）"被朗读出来。这是全项目最容易被用户直接感知的缺陷之一，且与 009 号同源 |
| **N05** | P2 | `ChatView.vue:513` vs `:138` | 两条通道对"上下文"的定义**相反**：WS 主链路只发 `slice(-2)[0]`（单条），HTTP 重生成链路发 `slice(0,-1)`（全量历史） | "首次发送没有多轮记忆，重新生成反而有"。且 `:514` 的注释声称"将所有历史消息全部传输"，与 WS 实际行为不符。这直接影响第 5 章的正式 AI 对话改造方案 |
| **N06** | P2 | `Connect.py:218-239`、`:304` | ACK 机制**未被删除**，只做了兼容判定 | 前端根本不发 ACK（用 `pendingRequests` + `message_id` 匹配）。`pending_ack_id` 只是"记住上一条 ID"，其它类型消息若 `message_id` 撞上就会被吞掉。V1.0 的建议是直接删除该分支 |
| **N07** | P2 | `Connect.py:242` | 未识别 `canceled_request` 消息类型 | `MessageType.ts:22` 定义了 `CANCEL = "canceled_request"`，后端不认 → 走 `message['type'] != 'client_query'` 发 `INVALID_MSG_TYPE`。**F08（停止按钮无效）在后端侧没有任何配套实现** |
| **N08** | P2 | `Connect.py:280` | 后端只产出 `status: "success"`，从不产出 `partial` / `failure` | 前端契约（`MessageType.ts:15`）与 `ServerResponse` 类型都要求 `status: string`，009 号缺陷的根因即在此。应作为独立契约项登记 |
| **N09** | P2 | `Integration.py:52`、`:135` | 角色匹配用 `f"{roleName}:\n" in lines[i]` 子串判断 | 角色名互为后缀时误命中（如同时存在 `Wendy` 与 `dy`）。应改为 `lines[i].strip() == f"{roleName}:"` |
| **N10** | P2 | `Integration.py:16-23` | `_lock_for` 只在**单进程内**有效 | `uvicorn --workers > 1` 或改用线程池后，锁直接失效，006 号缺陷回归。需在启动方式与扩容方案上显式约束，或把状态迁到 Redis / 数据库 |
| **N11** | P2 | `ChatView.vue:43` 等 6 处 | 静态资源用 `new URL('/src/assets/...')`，构建后不打进产物（与 F17 同一处，但**前端侧与 `settings.ts` 两侧都要改**） | 属跨层契约，只改一侧不收敛 |
| **N12** | P3 | `Text.py:17` | 每个请求同步读一次人设文件并 `print(role_prompt)` 全量输出 | 请求路径上做磁盘 I/O；日志中打印完整人设，属性能、隐私与日志卫生三重问题 |

---

## 四、测试资产的两个陷阱（动手前必读）

### 4.1 仍在"固化缺陷行为"的断言 —— 6 条用例 / 7 个断言点

以下用例**当前是绿灯**，但通过的方式是断言错误行为。**修改对应源码后必须同轮把断言翻转为正确值**，否则"修好了反而测试变红"。

| 用例 | 行号 | 当前断言 | 固化的是哪条缺陷 |
|---|---|---|---|
| `TC-LLM-01` | `test_service_and_state_cases.py:104` | `assert system_prompt["role"] == "assistant"` | N02 |
| `TC-IMG-01` | `:245`（另 `conftest:43`、`:359`、`:388`、`:414`、`:437` 均以 `""` 为契约） | `assert Image.static_images("Wendy", "mock-image") == ""` | B07 |
| `TC-IMG-02` | `:267` | 缺 1 张即全量重生成 7 张 | B07 关联（无去重节流） |
| `TC-TTS-02` | `:182` | TTS 超时后流程照常继续 | 009 / B24 |
| `TC-WS-01` | `test_websocket_cases.py:125`、`:120` | `tokens_used == len(FIXED_REPLY)`；`status == "success"` | B17 / N08 |
| `TC-WS-05`、`TC-WS-06` | `:164`、`:176` | 缺 `type`/`payload` 时预期 `SERVER_ERROR` | B16 |

**已确认翻转正确的**（无需再动）：`TC-TTS-04`（`:206`，xfail 标记已删）、`TC-EX-02`（`:399`，改断 `ValueError`）、`TC-EX-01`（`:375`，改名 `falls_back_without_crash`）、`TC-RES-03`（`:344`，改名 `falls_back_then_write_succeeds`）、`TC-CON-01`（`:420`，改名 `use_distinct_slots`）、`TC-WS-08`（`:200`，断四字段契约）、`TC-CFG-01/02/06`（`:227`/`:243`/`:263`，已改为只回一条 `PROCESS_ERROR`）、`TC-ACK-03`（`:320`）。

### 4.2 xfail 的 strict 语义

本仓库历史上有 `@pytest.mark.xfail(strict=True)`。`strict=True` 的语义是"**我断言它一定失败**"——用例一旦通过会报 XPASS 并在 strict 下降级为 FAILED。当前已无 xfail 标记，但**若为登记新缺陷而重新加上，必须记住：修好源码时要同步摘掉标记**。

---

## 五、面向"接入正式 AI 对话"的前置改造（重要）

用户需求是"长上下文 + 强压缩"，但**当前代码里根本没有上下文层**。换模型之前必须先把这一层补上，否则换任何模型都只有单轮记忆。

**现状证据链：**
1. `ChatView.vue:513` → `text: {role: ..., content: currentChatMessages.value.slice(-2)[0].content}` —— 只取倒数第二条（即刚发出的用户消息）。
2. `Text.py:35` → `full_prompt.append(prompt)` —— 只追加这一条。
3. `get_llm_response` 每次请求新建 `OpenAI` client，无会话状态、无持久化、无摘要。

**必须新增的四个组件：**

| 组件 | 职责 | 关键设计点 |
|---|---|---|
| 会话存储 | 按 `conversation_id` 保存完整消息序列 | 当前用 localStorage 存（F14 会爆 5 MB 上限）；建议迁到后端 SQLite/Postgres，前端只留索引 |
| 上下文组装 | 从存储取出历史，拼成 `messages` 数组 | 角色设定必须放 `role: "system"`（修 N02）；系统提示词与硬约束要**钉住不参与淘汰** |
| 压缩策略 | 超阈值时摘要旧轮次、保留近 N 轮原文 | 三种手段：① 服务端原生（Claude 的 compaction / context editing）；② 自建"摘要 + 滑窗"（用一个便宜模型做摘要器）；③ 关键事实外置到 KV / 记忆表，不依赖摘要携带 |
| 计费与观测 | 真实 token 统计 + 上下文水位监控 | 替换 B17 的 `len(response)`；对上下文占用率设阈值告警 |

**压缩策略的工程结论（有实证依据）：** 不要用"丢最旧消息"的家常做法——它会优先丢掉让对话连贯的系统级上下文。正确做法是"目标与硬约束钉住 + 旧轮次摘要 + 近几轮原文"，并按 **token 预算**触发（约 60% 窗口）而不是按轮数触发。

---

## 六、缺陷修复流程清单（可执行）

### 6.0 流程纪律（每次都适用）

```
1. 开工前：  git rev-parse HEAD 记录基线；确认工作区干净
2. 改代码前：先跑 ./scripts/run_module1_tests.sh，确认当前是 "34 passed"
3. 改代码时：PYTHONDONTWRITEBYTECODE=1（避免污染 7 个已入库的 .pyc）
4. 改代码后：若动了第 4.1 节列出的源码，同轮翻转对应断言
5. 收工前：  ./scripts/run_module1_tests.sh 必须回到 "34 passed"
             git diff --name-only -- backend/__pycache__ 必须无输出
             git status 检查是否误产生新文件
6. 未经明确许可：不执行 git commit / git push
```

### 6.1 批次一：P0 安全与可用性（阻塞上线）

| 序 | 编号 | 动作 | 验收标准 |
|---|---|---|---|
| 1 | B01 | 6 处密钥迁到 `.env`（`python-dotenv:45` 已在依赖里）；**并从 git 历史清除 + 轮换全部凭据** | `git grep` 搜不到任何 `sk-`/`AKLT`/`Bearer;`；旧凭据全部失效 |
| 2 | B02 | `/ws/chat` 加握手鉴权；`host` 改 `127.0.0.1`，对外走反向代理 | 未带凭据的连接被拒绝；`netstat` 不再对外暴露 8000 |
| 3 | B03 | `process_query` 保持同步逻辑但用 `asyncio.to_thread` / `run_in_threadpool` 包裹；`requests` 换 `httpx.AsyncClient`；图片生成放线程池 | 并发 2 个连接时，一个请求执行期间另一个仍能收到心跳与错误响应 |
| 4 | F01 + F02 | 关闭 `html: true` 或接入 DOMPurify 白名单；`${lang}` 走 `escapeHtml` | 发送 `<img src=x onerror=alert(1)>` 不弹窗；代码围栏语言名注入无效 |
| 5 | F06 | error 分支改用 `data.payload.message`（**D05 修复后此分支已可达，属回归风险**） | 触发一次服务端错误，助手气泡显示可读文案而非 `"error"` |
| 6 | 009 + N04 + N08 | TTS 返回值判空 → `status: "partial"` + `audio_available: false`；TTS 输入前剔除情绪括号；后端补齐 `partial`/`failure` | 让 TTS 抛超时，响应为 `partial` 且没有音频；朗读文本不含括号内容 |

### 6.2 批次二：P1 功能正确性与成本控制

| 序 | 编号 | 动作 | 联动改动 |
|---|---|---|---|
| 7 | B07 | `static_images` 资源齐全时返回**当前有效 URL**而非 `""`；`updateLinks` 加空值保护（空值不得覆盖已有 `Recent_Url`） | **必须同轮翻转 `TC-IMG-01`（`:245`）与 `conftest:43` 等 5 处 mock 契约** |
| 8 | N01 | 把 `updateLinks` 纳入 `_lock_for(roleName)`；或改成"index 只由 `_advance_index_only` 独占推进" | 新增并发用例：两个请求交错完成时，Records 的 index 必须等于 `max(两者推进值)`，不得回退 |
| 9 | N06 | 删除 ACK 分支（前端不依赖它） | `TC-ACK-01/02/03` 需同步改为直接连发两条请求 |
| 10 | N07 + F08 | 后端识别 `canceled_request` 并把对应 `message_id` 的任务取消；前端 `handleStop` 改发 WebSocket 取消帧 | 点"停止"后后端不再产生 TTS/图片调用（用 mock 计数验证） |
| 11 | N02 + N03 | 角色设定改 `role: "system"`；人设文件缺失时抛业务异常或显式降级告警 | **必须同轮翻转 `TC-LLM-01`（`:104`）** |
| 12 | B04 | `if delta.content != ""` → `if delta.content:` | 新增用例：末个 chunk 的 `content=None` 不抛异常 |
| 13 | B05 | 统一 `text` 字段为 `{role, content}` 对象（或后端做类型归一） | 两条链路各加一条契约用例 |
| 14 | B06 | 统一图片命名，明确"情绪名"与"槽位号"各自的用途与写入方 | 前端取图逻辑同步；静态完整性检查改为认同一套命名 |
| 15 | F03 | 从 `INLINE_MATH_RULES` 移除 `/\[([^\]]+)\]/`，或把 math 规则注册到 `link`/`image` 之后 | 新增用例：`[文本](url)` 必须渲染成链接 |
| 16 | F04 | `decoder.decode(value, {stream: true})` + 维护跨 chunk 行缓冲区 | 新增用例：一个中文字符被切成两个 chunk 时不出现替换字符 |
| 17 | F07 + F12 | 收敛到单一通道（建议统一走 WebSocket）；`handleRegenerate` 把 `isLoading` 判断提到 `splice` 之前 | 重生成后角色形象与语音同步；提前返回时消息不丢失 |
| 18 | F05 | 统一为 `imageModel_config`（或后端兼容两种写法） | TS 编译零报错 |
| 19 | B09 + N04 | 情绪提取改为只匹配**句首连续的两个括号**；映射表补英文情绪词；去掉裸 `except:` | 正文含"（笑）"时不误判；LLM 输出英文情绪时不再静默落 `neutral` |
| 20 | B18 + N11 | 路径改由 `__file__` 推导项目根或抽为配置项 | **同步调整测试里的 `monkeypatch.chdir(tmp/"backend")` 假设**，否则大量用例转红 |
| 21 | 011 | `pytest.ini` 加 `testpaths = tests`；`test_websocket.py` 标 `@pytest.mark.integration` | 裸 `pytest` 只收集 `tests/` 下的 34 条；不会触发真实计费 |
| 22 | B17 | 接入真实 tokenizer 统计 | **同步翻转 `TC-WS-01`（`:125`）** |

### 6.3 批次三：P2/P3 稳定性与工程卫生

| 分组 | 编号 | 说明 |
|---|---|---|
| 后端健壮性 | B11、B12、B13、B14、B15、B16（+`TC-WS-05/06` 断言翻转）、B19、B20 | 静默失败、无超时、正则笔误、异常分类不全、连接回收 |
| 后端工程 | B21、B22、B23、B24、N09、N10、N12 | SyntaxError、依赖声明、遗留脚本、子串匹配、单进程锁约束、日志卫生 |
| 前端稳定性 | F09、F10、F11、F13、F14、F15、F16、F18、F19、F20、F21、F22、F23 | 监听器与 Blob 泄漏、ID 冲突、持久化膨胀、输入法、异常未捕获、事件投递 |
| 前端工程 | F17、F24、F25、F26、F27、F28、F29、F30 | 构建后 404、调试入口、模板 ref、事件丢失、死代码清理、**补前端测试** |

**顺手可清的三项（改造成本极低）：** B21（`SyntaxError`）、B22 的 `websocat` 误声明、F30 的占位测试。

### 6.4 修复顺序的依赖关系（不要打乱）

```
批次一(6,009/N04/N08) ─┬─→ 批次二(7,B07) ─→ 批次二(8,N01)   [同一条资源链]
                       └─→ 批次二(17,F07/F12)
批次一(5,F06) ← 依赖 003(D05) 已完成
批次二(11,N02/N03) ─→ 第五章上下文层改造（角色设定必须先变成 system）
批次二(20,B18/N11) ─→ 必须在任何并发/多进程改造之前完成（否则路径会错到别处）
批次二(21,011) ─→ 应在任何人接手跑测试之前完成（否则可能产生真实账单）
```

**成本提示：** 批次一的第 3 项（N03/B03 阻塞事件循环）改动面最大，但它是"多用户可用"的前提；批次二的第 7、8、9 项涉及资源槽位与状态机，是唯一会产生"用户听到别人的语音"这类事故的路径，建议连成一个原子提交一起验证。

---

## 七、核对方法与边界

1. 逐文件重读后端 8 个运行期 `.py` 与前端 21 个源码文件，不依赖静态扫描工具。
2. `git show 4e9806f --stat` 与逐文件 diff 确认实际改动范围；`git status` 确认工作区状态。
3. `backend/tests/*.py` 逐用例核对断言，区分"已翻转"与"仍在固化缺陷"。
4. 前端 30 条逐条核验由子任务完成（覆盖 `ChatView.vue`、`ClientChat.ts`、`UseChatClient.ts`、`chat.ts`、`settings.ts`、`WebSocketManager.ts`、`MessageType.ts`、`SearchBar.vue`、`ChatInput.vue`、`SideBar.vue`、`SettingsPanel.vue`、`example.test.ts` 及全仓 grep）。
5. 两份上游文档均基于 `0c401fe`；本文档所有"已修复"判定均以 `4e9806f` 的实际代码为准，并给出文件行号。
6. **本轮未做任何代码修改，未执行任何 `git commit` / `git push`。**
