# LLMGal 前后端现存缺陷清单报告

| 项目名称 | LLMGal（Vue3 + FastAPI 对话式 Galgame 后端） |
|---|---|
| 报告版本 | V1.0 |
| 编制日期 | 2026-09-12 |
| 编制人 | xyfang |
| 扫描范围 | `backend/`（14 个 .py）、`frontend/src/`（21 个源码文件）、构建与测试配置、`artifacts/test-results/` |
| 代码基线 | `git HEAD = 0c401fe`，`backend/` 工作区零改动，脚本实测 **32 passed / 2 xfailed** |
| 关联材料 | `LLMGal_backend_34_test_cases.md`、`pytest-output.txt`、`module1-junit.xml`、`LLMGal_backend_程序修正指南.md` |

---

## 一、结论摘要

**扫描结果：共确认 53 条现存缺陷**，其中后端 29 条、前端 21 条、工程与测试资产 3 条。

| 等级 | 数量 | 含义 |
|---|---|---|
| P0 严重 | 5 | 凭据泄漏、接口无鉴权、XSS、服务不可用，须优先处理 |
| P1 高 | 16 | 功能不正确或造成直接经济损失，影响主流程 |
| P2 中 | 22 | 边界异常、资源泄漏、契约不一致，影响稳定性 |
| P3 低 | 10 | 可维护性、工程卫生、样式与死代码 |

**最要紧的五条：**

1. **D01 凭据硬编码** —— 火山引擎 AK/SK、TTS appid/token、第三方 LLM 中转站密钥共 6 处明文写在源码里，任何一个克隆本仓库的人都能直接盗用配额。
2. **D04 同步阻塞事件循环** —— `Connect.process_query` 是同步函数，内部却是 30 秒超时的 `requests.post` 与流式 LLM 调用，直接在 `async` 协程里执行。一条请求跑起来，**整个服务对其它连接停止响应**。
3. **D05 错误响应不符合前端契约** —— 后端 `send_error` 不带 `message_id`，前端 `isServerMessage` 因此判定为非法消息并丢弃。**所有错误提示都到不了用户眼前**，表现为"点了发送没反应"。
4. **D07 ACK 窗口吞掉下一条业务请求** —— 后端发完响应后无条件 `await receive_json()`。用户连续发两条消息时，第二条会被当成 ACK 吃掉且不重放，**消息永久丢失**。
5. **D12 静态模式清空图片 URL** —— `static_images` 在资源齐全时返回 `""`，`updateLinks` 随即把 Records 里的 `Recent_Url` 覆写成空值，导致下一次实时渲染必定失败并**回退到付费的文生图**。

**一条需要特别强调的判断：** 当前 34 条用例的"32 passed"**不等于 32 条正确**。其中至少 8 条是在用断言**固化缺陷行为**（例如 `TC-CON-01` 断言两个并发请求拿到同一个槽位），2 条用 `xfail` 钉住了已知缺陷。详见第六章。

---

## 二、后端缺陷清单

### 2.1 Connect.py（入口与协议层）

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D01a | P0 | `Connect.py:42` | `Authorization: "Bearer; _SRNKZhKXevBrx72wklF-D8NX7LGigGs"` 明文硬编码 | 与 `Voice.py` 共用同一 token，泄漏面翻倍 |
| D02 | P0 | `Connect.py:212-215`、`315` | `/ws/chat` 无任何鉴权，`uvicorn.run(host="0.0.0.0")` 全网卡监听 | 任意可达主机均可调用，直接消耗付费 LLM/TTS/图片额度 |
| D04 | P0 | `Connect.py:238` | `process_query` 为同步函数，内部调用同步 LLM 流、`requests.post(timeout=30)`、无超时 `requests.get`，却在 `async def websocket_chat` 中直接 `await` 之外的同步执行 | 单请求期间事件循环整体停摆，多用户场景下服务假死 |
| D08 | P1 | `Connect.py:237-258` | `except` 分支发送 `PROCESS_ERROR` 后未 `continue`，继续执行 `resp.response`；此时 `resp` 未绑定，抛 `UnboundLocalError`，被外层 `except` 捕获后再发一次 `SERVER_ERROR` | 一次失败产生两条矛盾错误响应；且第二条不含业务语义 |
| D34 | P2 | `Connect.py:197` | `respond.metrics["tokens_used"] = len(response)` 用字符数冒充 token 数 | metrics 失真；`test_websocket.py:45` 还断言其 `> 0`，掩盖了问题 |
| D50 | P3 | `Connect.py:286-288` | `finally: await websocket.close()` 被注释掉 | 依赖框架兜底关闭，连接状态与资源回收时机不确定 |
| D24b | P2 | `Connect.py:227,233` | 用下标访问必需键 `message['type']`、`message['payload']`，缺键时抛 `KeyError`；`except ValueError` 接不住 `KeyError` | 缺字段走不到预期的显式错误分支，而是冒泡成 `SERVER_ERROR`（TC-WS-05/06 记录的正是该行为） |

### 2.2 Integration.py（业务编排层）

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D10 | P1 | `Integration.py:117-121` 读、`200-203` 写 | 同一角色的 index 读-改-写之间**无任何互斥**。TC-CON-01 已用 `Barrier` 强制交错证明：两个并发请求都读到 `index=3`，都写回 `index=4` | 音频与图片文件互相覆盖，用户历史资源被踢掉；索引计数器丢步 |
| D11 | P1 | `Integration.py:158` | `Voice_Generation_through_http(...)` 的返回值被直接丢弃，成功路径返回文件路径、失败路径返回 `""`，调用方无法区分 | TTS 失败后仍返回 `status=success`，前端去播放不存在的 mp3（详见 D22、D33） |
| D12 | P1 | `Integration.py:198,203` + `Image.py:251` | `realTimeGeneration=False` 且静态资源齐全时，`static_images` 返回 `""`，`updateLinks(roleName, "", updatedIndex)` 把 Records 的 `Recent_Url` 覆写为空 | 下一次实时渲染因 `imgurl=""` 必然失败，回退到付费文生图，**造成非预期计费** |
| D13 | P1 | `Integration.py:117-132` | `except` 只覆盖 `FileNotFoundError` 与 `IOError`。角色记录缺失时 `re.findall` 返回空列表，`matches[0]` 抛 `IndexError` 直接冒泡（TC-EX-01 固化）；正则 `index:(\d+)` 使非数字索引整条失配，同样提前 `IndexError`（TC-EX-02 xfail） | 角色未登记即崩溃；索引脏数据在正确位置（`int()` 处）失败之前就炸掉 |
| D17b | P1 | `Integration.py:200` | `index = int(index)` 位于 LLM 调用、TTS 调用、图片生成**之后** | 索引脏数据导致"钱已经花完才失败"，无回滚 |
| D36 | P2 | `Integration.py:85-95` | `updateLinks` 读-改-写无锁；`lines[i+1]`、`lines[i+2]` 无长度检查；角色匹配失败时**静默无操作** | 与 D10 叠加放大覆盖问题；匹配失败无任何信号返回 |

### 2.3 Voice.py（语音合成层）

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D01b | P0 | `Voice.py:17-18`、`116`、`213` | `appid`、`token` 明文硬编码，且 `Authorization` 头在三处重复同一 token | 密钥泄漏 |
| D22 | P2 | `Voice.py:195` | `base64.b64decode(audio)` 默认 `validate=False`，`"%%%%"` 被静默解为 `b''` 且不抛异常，随后照常写出 0 字节文件并**返回文件路径** | TC-TTS-04 的根因；前端拿到"成功"路径却播放失败，属于静默数据损坏 |
| D11b | P2 | `Voice.py:164-174` | `parse_response` 遇到服务端错误帧（`message_type == 0xf`）只打印日志后 `return True`，被上层当作正常结束 | TTS 服务端报错被吞，业务层认为音频已生成 |
| D33 | P2 | `Voice.py:22`、`237` | `reqid` 是模块级全局变量，HTTP 路径始终使用同一个 `reqid`，而 `use_cache` 为 `True` | 不同文本可能命中同一缓存音频，出现"回复内容变了但语音没变" |
| D25b | P3 | `Voice.py:115` | `file_to_save = open(savePath, "wb")` 在 `async with websockets.connect(...)` 之前打开，异常路径无 `finally` 关闭 | 连接失败时文件句柄泄漏 |
| D46b | P3 | `Voice.py:36-61`、`187-189` | `Voice.request_confirmation` 用数字索引匹配音色，与 `Integration.request_confirmation` 的字符串口径完全不同，且该函数与 `Voice_Generation` 在项目内**从未被调用** | 双份实现并存，改动容易改错一处 |

### 2.4 Text.py / Image.py（模型与图像层）

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D01c | P0 | `Text.py:38`；`Image.py:9-10`；`image_emotions.py:4-5` | 第三方中转站 API Key（`sk-Tk2R...`）、火山引擎 AK/SK 明文硬编码 | 密钥泄漏，且 `Image.py` 与 `image_emotions.py` 各存了一份 |
| D18 | P1 | `Text.py:54` | `if delta.content != "":` —— 推理模型首个 chunk 的 `content` 常为 `None`，`None != ""` 为真，进入分支后执行 `answer_content += None` 抛 `TypeError` | 使用 DeepSeek-R1 等推理模型时整条回复失败 |
| D19 | P1 | `Text.py:35` + `UseChatClient.ts:77` vs `ChatView.vue:501` | `full_prompt.append(prompt)` 要求 `text` 是 `{role, content}` 字典；前端两条链路分别传**字符串**和**对象** | 传字符串的链路会让 OpenAI SDK 直接报类型错误，请求全失败 |
| D27 | P2 | `Image.py:83`、`85-88` | `pattern_appearance = r'Appearance Details:\s*(.+?)(?=\0\|$)'` 中 `\0` 是 **NUL 字符笔误**（本意应为 `\n`）；且 `subject_description[0]` / `appearance_details[0]` 未判空 | 角色描述文件缺失或格式不符时 `findall` 返回 `[]`，索引越界抛 `IndexError` |
| D15 | P1 | `Image.py:108,159` vs `227-235` | 同一角色的图片存在两套命名：`{role}_{数字}.jpg`（实时路径）与 `{role}_{情绪名}.jpg`（静态路径）。前端 `ChatInput.vue:223` 按情绪名取头像，`ChatView` 的音频/图片按数字取 | 输入框头像与聊天区图片来自不同文件、不同步；静态完整性检查只认情绪名那 7 张 |
| D40 | P2 | `Image.py:34,189,205` | `requests.get(url, stream=True)` 无 `timeout`；`visual_service.cv_process` 无超时控制 | 下载/生成卡住时线程无限等待，叠加 D04 直接拖垮服务 |
| D35 | P2 | `Integration.py:137-138`、`56-80` | 情绪提取用 `\((.*?)\)` 抓**所有**括号，正文中的"（笑）""（1）"会被误当情绪；且映射表只认中文情绪词，LLM 输出英文时静默落到 `neutral` | 情绪识别错误或静默失效，图片与语音情绪不匹配 |
| D27b | P3 | `Image.py:132,191,207` | 直接取 `resp['data']['image_urls'][0]`，未校验响应结构 | API 返回错误结构时抛 `KeyError`/`IndexError`，落进"URL 过期"的兜底分支，误触发付费重生成 |

### 2.5 工程与测试资产

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D17 | P1 | `pytest.ini`（仅 3 行，无 `testpaths`） | 裸跑 `pytest` 会收集 `backend/test_websocket.py`，该文件 `:9` 直连 `ws://localhost:8000/ws/chat` 并断言真实 LLM 输出 | 后端服务在跑时执行测试 = **真实调用 LLM/TTS/图片 API 并计费** |
| D37 | P2 | `TestSubject.py:1` 与 `:5` | `from volcenginesdktransitrouter import ...` 出现在 `from __future__ import print_function` **之前**，违反语法规则 → `SyntaxError`；`:13-21` `configuration` 被赋值两次，前四项配置全部失效 | 文件无法导入；且该文件是火山引擎 ECS 示例代码，与项目业务无关，依赖的 `volcenginesdk*` 均不在 requirements 中 |
| D45 | P3 | `requirements.txt` | `websocat==1.13.0` 是 CLI 工具而非可导入包；`Flask`/`mysqlclient`/`PyMySQL`/`redis`/`redis-om`/`SQLAlchemy`/`loguru` 在代码中零 import；缺 `volcenginesdk*`；把 `pytest`/`pytest-asyncio` 混在生产依赖；`fastapi 0.95.1 + pydantic 1.10.7` 与 Python ≥3.12 不兼容 | 依赖声明与真实需求脱节，环境复现困难 |
| D53 | P3 | `image_emotions.py` | 一次性调试脚本，硬编码了已过期的签名 URL（`x-expires=1752047352`），与 `Image.py` 重复定义 AK/SK | 遗留代码，误导后续维护 |
| D32 | P2 | `Integration.py:86,89,117`、`Text.py:14`、`Voice.py:113,193`、`Image.py:48,72,108,159,220` | **共 13 处** `../frontend/src/assets/...` 相对路径，依赖进程启动时的当前工作目录 | 从项目根目录启动 `uvicorn` 立即 `FileNotFoundError`；测试靠 `monkeypatch.chdir()` 绕开，掩盖了问题 |

---

## 三、前端缺陷清单

### 3.1 工具层

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D03 | P0 | `utils/markdown.ts:9` + `ChatMessage.vue:167,164`、`SearchBar.vue:207,214` | MarkdownIt 开启 `html: true` 且无任何消毒，渲染结果经 `v-html` 注入。内容来源是 LLM 回复与用户输入 | 任一环节返回 `<img src=x onerror=...>` 即可执行任意脚本 |
| D03b | P1 | `utils/markdown.ts:22-24` | 高亮函数把 `${lang}` 直接拼进 `class="${lang}"`，`lang` 取自代码围栏标记且未转义 | 围栏语言名是第二个注入点 |
| D06 | P1 | `utils/markdown.ts:68-98` | `INLINE_MATH_RULES` 第二条 `/\[([^\]]+)\]/` 注册在 `before('escape')`，优先级高于 markdown-it 内置的 `link`/`image` 规则。解析 `[文本](url)` 时 `[文本]` 被抢先切成 KaTeX 公式，剩余 `(url)` 沦为纯文本 | **所有 Markdown 链接与图片全部渲染失败**；`ChatInput` 生成的 `![name](data:image/...)` 附件与 `formatImageMessage` 生成的图片消息均无法显示 |
| D16 | P1 | `utils/messageHandler.ts:111`、`153-156` | `decoder.decode(value)` 未使用 `{stream: true}`，跨 chunk 的多字节 UTF-8（中文）被截断成替换字符；同一行 JSON 被 chunk 边界切开时仅 `console.error` 后丢弃 | 流式回复中文乱码、丢字，且用户无从察觉 |
| D23 | P2 | `utils/WebSocketManager.ts:122-125` | `off()` 内部 `const wrapper = data => handler(data as T)` 每次新建函数，`Set.delete` 比较的是新引用，**永远删不掉**。连带 `ClientChat.ts:105-109` 的 progress 监听器无法清理 | 历史请求的进度回调全部存活，进度串台；内存持续增长。（当前调用点位于尚未启用的 `LLMClient` 链路，故暂未显性发作） |
| D42 | P2 | `utils/WebSocketManager.ts:144-151`、`51-55`、`136-138` | `emit` 中 `if (typeof data !== 'undefined')` 才回调，**合法事件若不带 payload 会被静默丢弃**；`error` 事件既由 socket 原生 error 触发，也由服务端 error 消息触发，两者语义不同却共用通道 | 事件投递不可靠；`LLMClient.handleError` 会把任意服务端错误升级为"拒绝全部 pending 请求" |
| D52 | P3 | `utils/MessageType.ts:88`、`100-110` | 函数名拼写错误 `isClientMessgage`；`isServerMessage` 未校验 `status`，而 `ServerMessage` 类型声明要求 `status: string` | 命名混乱；类型声明与运行时校验不一致 |
| D31 | P2 | `stores/settings.ts:20,24`、`ChatInput.vue:43`、`ChatView.vue:43`、`SettingsPanel.vue:381` | 静态资源统一用 `new URL('/src/assets/...', import.meta.url)`。以 `/` 开头是 public 路径语义，Vite 在 dev 下能解析，**构建后不会被打包**；`vite.config.ts` 也未配置对应代理或拷贝 | `npm run build` 产物中角色图片、语音、角色文档全部 404 |
| D14 | P1 | `utils/MessageType.ts:41` vs `stores/ClientChat.ts:86`、`stores/UseChatClient.ts:81` | 类型定义与后端契约均为 `imageModel_config`，`ClientChat`/`UseChatClient` 链路写成 `imageMode_config` | 该链路发出的 payload 缺少后端必填字段 `imageModel_config`，Pydantic 校验失败；同时 TS 类型层面也已报错 |

### 3.2 状态层

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D25 | P2 | `stores/chat.ts:106`、`utils/messageHandler.ts:61`、`stores/chat.ts:61` | `id: Date.now()` 毫秒级取 ID，同毫秒内连续添加消息必然冲突；`createConversation` 亦用 `Date.now().toString()` | `v-for :key` 冲突导致 DOM 复用错乱；`findIndex(m => m.id === ...)` 命中错误消息；叠加 `splice(index, 2)` 的"成对删除"假设，会**连删无关消息** |
| D28 | P2 | `stores/chat.ts:194-197`、`stores/settings.ts:154-159` | `persist` 把含 base64 图片的完整 `conversations` 写入 localStorage（5 MB 上限）；`settings` 的持久化把 `apiKey` 一并明文落盘 | 长会话触发 `QuotaExceededError` 并使持久化失效；API Key 可被同域脚本或本地读取 |
| D29 | P2 | `stores/ClientChat.ts:181-202` | `cancelRequest` 先 `delete` 再 `reject(new Error('请求已被用户取消'))`，把用户主动取消当作异常抛出 | 调用方按错误处理，弹出错误提示（当前位于未启用链路） |
| D46a | P3 | `stores/ClientChat.ts:204-213` | `retryQueue` 始终为空数组，`handleReconnect` 永远空转 | 死代码 |
| D46c | P3 | `stores/UseChatClient.ts`、`stores/ClientChat.ts` | 整条 `useChatClient` / `LLMClient` 链路**全项目零引用**，其中的缺陷（D23/D29/D30/D14）均不会显性发作，但会误导维护者以为 WebSocket 通信走的是这条链 | 死代码，且与 `ChatView` 中的实际实现重复 |
| D30 | P2 | `stores/UseChatClient.ts:105,124-127` | `handleError` 签名为 `(error, msg)`，调用处只传一个参数，`msg` 恒为 `undefined`，`error.value = undefined` | 错误提示永不显示（当前位于未启用链路） |
| D46d | P3 | `utils/WebSocketManager.ts:158-186` | `startHeartbeat` 的调用被注释、`stopHeartbeat` 无调用方、`reconnect` 仅在心跳中超时分支使用；`lastHeartbeat` 赋值后无实际作用 | 心跳机制整体失效，30 秒超时判断形同虚设 |

### 3.3 视图与组件层

| 编号 | 等级 | 位置 | 缺陷描述 | 影响 |
|---|---|---|---|---|
| D20 | P1 | `views/ChatView.vue:415` | 收到 error 消息时执行 `chatStore.updateLastMessage(data.status, '')`，把整体状态字段当正文写入。正确来源是 `data.payload.message` | 助手气泡显示 "error"/"success" 之类无意义内容（该分支当前因 D05 上游拦截而不可达，修复 D05 后会立即暴露） |
| D21 | P1 | `views/ChatView.vue:640` vs `:330` | 首次发送走 `handleSendbyWebSocket`（WebSocket，含音频与表情联动），"重新生成"走 `handleSend`（HTTP，无音频无表情） | 同一功能两条通道能力不一致，重新生成后角色形象与语音不同步；`handleMessageUpdate` 成为死代码 |
| D09 | P1 | `views/ChatView.vue:342-349` | `handleStop` 只调用 `chatApi.abortRequest()`（中止 fetch），而实际发送通道是 WebSocket | 点"停止"只重置了本地状态，**后端请求继续执行并计费**，音频/图片照常生成 |
| D24 | P2 | `components/SearchBar.vue:112-119` | 在 `setup` 顶层给 `document.documentElement` 注册 `click` 监听，**从未移除**（对比 `handleShortcut` 有 `onUnmounted` 清理） | 组件每次创建都叠加一个监听器，内存与回调泄漏 |
| D26 | P2 | `views/ChatView.vue:316-338` | `handleRegenerate` 先 `splice(index - 1, 2)` 删除消息，之后才 `if (isLoading.value) return` | 提前返回时消息已被删除且未重新发送，**内容丢失** |
| D38 | P2 | `components/ChatInput.vue:229` | `@keydown.enter.exact.prevent="handleSend"` 未判断输入法组合态（`isComposing`） | 中文输入法选词时按回车会**误发送半截内容** |
| D39 | P2 | `views/ChatView.vue:368-370`、`components/SettingsPanel.vue:395-399` | `audio.value.play()` 返回的 Promise 无 `catch`，且音频文件不存在时 `canplay` 不触发 | 浏览器控制台抛 `Uncaught (in promise) DOMException`，自动播放被策略拦截时无任何降级提示 |
| D41 | P2 | `views/ChatView.vue:592-597`、`433-443` + `utils/WebSocketManager.ts:59-74` | `onBeforeUnmount` 被注释掉，组件卸载不断开连接；同时 `disconnected` 事件里又主动 `reconnect()`，与 `WebSocketManager` 自带的退避重连叠加 | **双重重连**，连接抖动时可能建立多条连接 |
| D43 | P2 | `views/ChatView.vue:483` | `currentChatMessages.value.slice(-2)[0].content.trim()` 未判空 | 消息数不足 2 条时 `undefined.trim()` 抛 `TypeError`（正常路径因先行 push 两条而侥幸规避） |
| D27c | P2 | `components/ChatInput.vue:85-87,207` | `getPreviewUrl` 在模板中调用 `URL.createObjectURL(file)`，每次重渲染都生成新 Blob URL 且**从不 `revokeObjectURL`** | 上传多图时内存持续泄漏 |
| D47 | P3 | `components/ChatInput.vue:224`、`SettingsPanel.vue:640` | `v-if="!getImageUrl(...)"` —— 函数恒定返回非空 URL 字符串，条件恒为假 | `.place` 与 `.avatar-placeholder` 占位提示**永远不会显示** |
| D47b | P3 | `components/ChatInput.vue:313,335` | `.image-preview .el-input` 选择器与真实 DOM 结构不符；`.token-counter` 样式写在 `.input-wrapper` 内而节点在其外 | 对应样式失效 |
| D47c | P3 | `components/SideBar.vue:212-246` | 用 `.el-button { background-color: #2196F3 }` 覆盖子组件样式，未区分 `type` | 删除按钮失去 danger 红色语义，危险操作视觉提示消失 |
| D48 | P3 | `components/SideBar.vue:94`、`61-68` + `93` | 模板 `ref="editInputRef"` 引用了**未声明**的 ref；重命名时 `@keydown.esc` 设 `editingId = null`，但 `@blur` 仍会触发 `saveRename` | 控制台警告；按 Esc 取消后仍可能保存新标题 |
| D49 | P3 | `views/ChatView.vue:458-480` | `initWebSocket` 先 `await websocketManager.connect()`，再调用 `handleConnectionEvents()` 注册监听；而 `WebSocketManager.connect` 在 `open` 回调内先 `emit('connected')` 后 `resolve`，监听器注册时机**晚于事件触发** | `connected` 事件永久丢失，`connectionStatus` 停留在 `connecting`（当前模板未使用该状态，故暂无可见影响） |
| D51 | P3 | `views/ChatView.vue:569,572-590,649-652` | `runTests` 调试按钮与 `.debug-panel` 保留在模板中，可手动伪造 `assistant_response` 注入 store | 生产环境存在调试入口 |
| D44 | P3 | `src/_tests_/example.test.ts`（全文 7 行） | 前端唯一的测试文件只断言 `expect(1 + 1).toBe(2)`。`@vue/test-utils`、`jsdom`、`vitest` 均已安装但**零组件测试、零 store 测试** | 前端约 4600 行代码处于完全无测试保护状态 |

---

## 四、跨层契约缺陷汇总

以下四条需要前后端一起改，单独改一侧无法收敛：

| 编号 | 契约点 | 后端 | 前端 | 后果 |
|---|---|---|---|---|
| D05 | 错误消息结构 | `send_error` 输出 `{type, code, message, detail?}`，**无 `message_id`、无 `status`**（`Connect.py:293-298`） | `isServerMessage` 要求 `typeof msg.message_id === "string"`（`MessageType.ts:107`） | 校验失败 → 走 `invalid_message` 分支 → 而该事件**无人监听** → **错误提示 100% 丢失** |
| D14 | 图片模型配置字段 | `ClientRequest.imageModel_config`（`Connect.py:138`） | 类型定义为 `imageModel_config`，但 `ClientChat`/`UseChatClient` 写 `imageMode_config` | Pydantic 必填字段缺失，`VALIDATION_ERROR` |
| D19 | 用户文本字段 | `full_prompt.append(prompt)` 要求 `{role, content}` 字典（`Text.py:35`） | `ChatView.vue:501` 传对象（正确）；`UseChatClient.ts:77` 传字符串 | 走字符串的那条链路必失败 |
| D34 | 计费口径 | `tokens_used = len(response)` 为字符数（`Connect.py:197`） | 前端 `tokenCount` 直接累加展示（`ChatInput.vue:258`） | 双方共用一个语义错误的指标，用户看到的 Token 数没有意义 |

---

## 五、缺陷分布

| 层 | 缺陷数 | 细分 | 主要问题类型 |
|---|---|---|---|
| **后端** | **32** | `Connect.py` 7；`Integration.py` 6；`Voice.py` 6；`Text.py`/`Image.py`/`image_emotions.py` 8；工程与路径 5 | 鉴权、阻塞、错误协议、并发覆盖、异常路径、密钥、静默失败、正则笔误、相对路径 |
| **前端** | **33** | `utils/*.ts` 9；`stores/*.ts` 7；`views/*.vue`、`components/*.vue` 17 | XSS、公式规则、SSE 解码、事件系统、ID 冲突、持久化、停止无效、双通道、监听器泄漏、输入法、样式 |

按层级看，**后端缺陷集中在"与外部服务交互的边界处理"**（超时、返回值校验、异常分类、并发互斥），**前端缺陷集中在"资源生命周期与状态标识"**（监听器不回收、ID 冲突、持久化膨胀、Blob URL 泄漏）。两类问题的共同根因是同一个：**项目没有任何针对这些路径的自动化测试**。

---

## 六、测试盲区分析

这一章解释"为什么 32 条通过了，缺陷还在"。

### 6.1 被 `xfail(strict=True)` 钉住的两条（已知缺陷，主动记录）

| 用例 | 缺陷编号 | 实测根因 |
|---|---|---|
| `TC-TTS-04` | D22 | `b64decode` 默认 `validate=False`，非法字符被静默丢弃，函数照常返回文件路径并写出 0 字节 mp3 |
| `TC-EX-02` | D13 | 正则 `index:(\d+)` 让 `index:abc` 整条失配，`matches[0]` 提前抛 `IndexError`，`int()` 处预期的 `ValueError` 永远等不到 |

这两条是**健康的**——缺陷被显式登记。修改源码后必须同步删除 `xfail` 标记，否则用例会变成 `XPASS` 并被判定为 FAILED。

### 6.2 被断言"固化"为期望行为的缺陷（更危险）

以下用例**通过**了，但它通过的方式是断言当前（错误的）行为。它们会在你修复缺陷时**变成红灯**，形成修复阻力：

| 用例 | 断言内容 | 被固化的缺陷 |
|---|---|---|
| `TC-CON-01` | `voice_slots == ["3","3"]`、`updates == [("Wendy","","4"),("Wendy","","4")]` | D10 并发覆盖同一槽位 |
| `TC-EX-01` | `pytest.raises(IndexError)` | D13 角色记录缺失抛 `IndexError` 而非受控降级 |
| `TC-RES-03` | `pytest.raises(FileNotFoundError)` | D13/D12 Records 缺失时静态图片已生成（已付费）才失败 |
| `TC-LLM-01` | `system_prompt["role"] == "assistant"` | 用 `assistant` 角色承载系统提示词（语义错误，应为 `system`） |
| `TC-IMG-01` | `static_images(...) == ""` | D12 静态模式返回空 URL，进而清空 Records |
| `TC-IMG-02` | `len(original_calls) == 1`、`len(emotional_calls) == 6` | 缺 1 张图即**全量重生成 7 张**（1 次文生图 + 6 次图生图），无去重节流 |
| `TC-TTS-02` | TTS 超时后 `image_calls` 正常、Records 正常更新 | D11 TTS 失败静默但响应仍为 `success` |
| `TC-WS-05`/`TC-WS-06` | 预期"访问缺失键产生异常并尝试发送 `SERVER_ERROR`" | D24b 用下标访问必需键，而非显式字段校验 |

**结论：修复 D10、D12、D13、D11 时，必须同步重写对应用例的断言，否则"修好了反而测试变红"。**

### 6.3 覆盖率盲区与缺陷落点高度吻合

| 文件 | 覆盖率 | 未覆盖区段 | 与缺陷的对应关系 |
|---|---|---|---|
| `Voice.py` | 31% | `37-61`、`65-124`、`127-183` | 二进制协议解析整段未被触达 → D11b、D33 因此无人发现 |
| `Image.py` | 40% | `29-45`、`48-66`、`70-88`、`92-135` | 图片下载与生成路径整段 mock 掉 → D27、D40 无覆盖 |
| `Text.py` | 76% | `18-21`、`48-49`、`61-62` | 缺 `48-49`（空 choices 分支）与 `61-62` → D18 的 `None` 分支恰好落在边缘 |
| `Connect.py` | 73% | `22-26`、`30-32`、`40-70`、`210`、`264-267`、`310-315` | 内层连接管理、`send_error` 尾部未被覆盖 → D05、D09 无覆盖 |
| `Integration.py` | 83% | `67-80`、`129-132`、`151-154` | 正是异常回滚与 Records 写回路径 → D13、D12 的落点 |
| **TOTAL** | **56%** | 243 条语句从未执行 | 未覆盖区 = 外部服务交互层，正是缺陷最密集处 |

一句话：**覆盖率的最低点，就是缺陷的高发区。** 测试为了隔离与可重复性把外部交互层整体替换为假实现，代价是这些代码的真实行为从未被验证。

---

## 七、修复优先级路线图

### 第一批：P0（安全与可用性，建议立即处理）

| 编号 | 动作 | 备注 |
|---|---|---|
| D01 | 把 6 处密钥迁到环境变量或 `.env`（`python-dotenv` 已在依赖中），并从 git 历史中清除 | 密钥已进入版本历史，**仅改源码不够**，须轮换全部凭据 |
| D02 | `/ws/chat` 增加握手鉴权；`host` 改为 `127.0.0.1`，对外统一走反向代理 | |
| D03 | Markdown 渲染关闭 `html: true`，或接入 DOMPurify 白名单 | 同时修 `markdown.ts:22-24` 的 `lang` 未转义 |
| D04 | `process_query` 改为 `async`，`requests` 换 `httpx.AsyncClient`，OpenAI 换 `AsyncOpenAI`；图片生成放入 `run_in_executor` | 改动面最大，但这是多用户可用的前提 |
| D05 | `send_error` 补齐 `message_id` 与 `status`；`ChatView` 注册 `invalid_message` 监听作为兜底 | 前后端一起改 |

### 第二批：P1（功能正确性与成本控制）

| 编号 | 动作 |
|---|---|
| D06 | 从 `INLINE_MATH_RULES` 移除 `/\[([^\]]+)\]/`，或把 math 规则改到 `link`/`image` 之后注册 |
| D07 | 删除 ACK 等待，或改为按 `message_id` 建索引、ACK 不匹配时**回填**到待处理队列 |
| D08 | `except` 分支补 `continue`；或把响应构造整体移入 `try` 的 `else` 子句 |
| D09 | `handleStop` 增加 WebSocket 侧的 `canceled_request` 发送 |
| D10 | 为 Records 的读-改-写加锁（`threading.Lock` 或按角色名分片），或改为原子重写 |
| D11 | 校验 TTS 返回值：为空则响应用 `status=partial` 并附 `audio_available: false` |
| D12 | `static_images` 资源齐全时返回**当前有效 URL** 而非 `""`；`updateLinks` 加空值保护 |
| D13 | 正则改为 `index:([^\n]*)`；`matches` 判空后走受控降级；`int()` 转换提到外部调用之前 |
| D14 | 统一为 `imageModel_config`，或后端兼容两种写法 |
| D15 | 统一图片命名规则，明确"情绪名"与"槽位号"各自的用途 |
| D16 | `decoder.decode(value, {stream: true})`；维护跨 chunk 的行缓冲区 |
| D17 | `pytest.ini` 加 `testpaths = tests`；把 `test_websocket.py` 标记为 `@pytest.mark.integration` |
| D18 | 改为 `if delta.content: `，空值安全 |
| D19 | 统一 `text` 字段为对象，或后端做类型归一 |
| D20 | 改用 `data.payload.message` |
| D21 | 收敛到单一通道（建议统一走 WebSocket） |
| D32 | 路径改为基于 `__file__` 推导的项目根，或抽到配置项 |
| D34 | 接入真实 tokenizer 统计 |

### 第三批：P2 / P3（稳定性与工程卫生）

| 分组 | 涵盖缺陷 | 说明 |
|---|---|---|
| 后端健壮性 | D22、D24b、D25b、D27、D27b、D33、D35、D36、D40、D11b | 静默失败、无超时、正则笔误、异常分类不全 |
| 后端工程 | D32、D34、D37、D45、D46b、D50、D53 | 相对路径、计费口径、依赖声明、遗留脚本 |
| 前端稳定性 | D23、D24、D25、D26、D27c、D28、D29、D30、D31、D38、D39、D41、D42、D43、D46a、D46c、D46d | 监听器与 Blob 泄漏、ID 冲突、持久化膨胀、输入法、异常未捕获 |
| 前端工程与样式 | D44、D47、D47b、D47c、D48、D49、D51、D52 | 测试形同虚设、选择器失效、模板 ref、调试入口、命名拼写 |

其中 **D37 的 `SyntaxError`、D45 的 `websocat` 误声明、D44 的占位测试** 三项改动成本极低，建议在任一批次里顺手清理。

---

## 八、附录：扫描方法与边界说明

**扫描方法**

1. 逐文件通读 `backend/`（14 个 .py，约 1900 行）与 `frontend/src/`（21 个源码文件，约 4600 行），不依赖静态扫描工具。
2. 交叉验证：对每一处疑似问题回到调用方与实际数据流确认，剔除误报。举例——`ChatView.vue:504` 的 `modelText.value` 初看像"对普通对象误用 `.value`"，实际 `modelText` 是 `ModelOption` 对象，`.value` 正是其模型标识字段，**结果正确，不计入缺陷**。
3. 与既有材料对齐：`34_test_cases.md` 的用例编号、`pytest-output.txt` 的实际结果、`module1-junit.xml` 的用例状态、覆盖率报告的未覆盖行号。
4. 依赖关系核实：通过全仓检索确认 `useChatClient` / `LLMClient` 零引用，据此调整了 D23、D29、D30 的等级并标注"当前链路未启用"。

**未纳入缺陷的观察项（供参考，不计入 65 条）**

- `App.vue` 中 `.app-container` 样式与 `ChatView.vue` 同名类重复定义，后者生效，前者为冗余。
- `ChatMessage.vue` 中 `markdownBody` ref 声明后未使用。
- `ChatInput.vue:146` `newline` 为空函数，仅用于拦截 `Shift+Enter`，属可接受写法。
- `SearchBar.vue:18` `searchInput` 的类型标注为 `InstanceType<typeof HTMLInputElement>`，与实际绑定的 `el-input` 组件不符（类型层面问题，运行无影响）。
- `vite.config.ts:16` 用 `process.env.NODE_ENV` 判断生产环境，Vite 实际以 `mode` 为准，该分支基本不会触发。
- `pytest.ini` 中 `asyncio_mode` 与 `addopts = --asyncio-mode=auto` 重复配置。

**本次扫描未做任何代码修改，未执行任何 `git commit` / `git push`。工作区改动仍只有 `scripts/run_module1_tests.sh` 一项（先前策略 A 的加固，待你审核）。**
