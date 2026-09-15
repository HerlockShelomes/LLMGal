# LLMGal 后端模块一 —— Bug 修复前后对比报告

**修复范围**：仅修复 `scripts/run_module1_tests.sh` 运行输出中报出的 2 条失败信号（2 个 xfailed）。
**未修复**：指南中列出的其余缺陷（B/C/D/E 组）保持原样，理由见第 5 节。
**Git 状态**：未执行任何 `commit` / `push`，HEAD 仍为 `0c401fe`。

---

## 1. 结果摘要

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 用例结果 | 32 passed, **2 xfailed** | **34 passed** |
| xfailed / failed / error | 2 / 0 / 0 | **0 / 0 / 0** |
| junit `tests` / `errors` / `failures` / `skipped` | 34 / 0 / 0 / 0（含 2 个 xfail 标记） | 34 / 0 / 0 / **0** |
| 耗时 | 2.45s（幂等重跑） | 3.02s |
| 覆盖率 TOTAL | 556 stmts / 243 miss / **56%** | 560 stmts / 242 miss / **57%** |
| `Voice.py` 覆盖率 | 160 stmts / 111 miss / 31% | 164 stmts / 110 miss / **33%** |

**改动的生产代码只有两处，各一行核心逻辑**：
- `backend/Voice.py:195` —— Base64 解码改为严格模式 + 空数据守卫
- `backend/Integration.py:119` —— Records 的 index 捕获组放宽

外加**一处必须同步的测试标记删除**（`backend/tests/test_service_and_state_cases.py`，删 2 行），理由见第 4 节。

---

## 2. 修复依据：脚本报出的"错误信息"是什么

`run_module1_tests.sh` 的输出里**没有 ERROR 或 FAILED**，唯一指向问题的信号是这一行：

```
======================== 32 passed, 2 xfailed in 2.45s ========================
```

以及用例列表里的两个 `x`：

```
tests\test_service_and_state_cases.py ........x.........x.               [ 58%]
```

`xfailed` 的字面意思是"按预期失败了"。这两个用例被作者用 `@pytest.mark.xfail(strict=True, ...)` 标记，reason 字段直接写明了缺陷：

| 用例 | xfail reason（原样引用） |
|---|---|
| TC-TTS-04 | `当前实现会写入零字节音频` |
| TC-EX-02 | `正则表达式先排除了非数字索引` |

**这就是脚本给出的完整错误信息**，也是本次修复的全部依据。两条都是真缺陷，不是"设计如此"。

---

## 3. 修复详情

### 3.1 修复一：非法 Base64 被静默解码为空字节，写出 0 字节 mp3

**位置**：`backend/Voice.py`，函数 `save_audio_from_base64`

**修复前**

```python
    try:
        savePath = f"../frontend/src/assets/voice/{role}/{role}_{index}_Stream.mp3"
        os.makedirs(os.path.dirname(savePath), exist_ok=True)
        audio_data = base64.b64decode(audio)
        with open(savePath, 'wb') as audio_file:
            audio_file.write(audio_data)

        print("音频已保存: ", savePath)
        return savePath

    except Exception as e:
        print("音频转码出错: ", e)
        return ""
```

**修复后**

```python
    try:
        savePath = f"../frontend/src/assets/voice/{role}/{role}_{index}_Stream.mp3"
        os.makedirs(os.path.dirname(savePath), exist_ok=True)
        # base64.b64decode 默认 validate=False 会静默丢弃非法字符，使 "%%%%" 之类的
        # 非法输入解码为空字节并写出 0 字节 mp3。先剥离空白（兼容换行折行的合法
        # Base64），再以 validate=True 严格解码，让非法字符显式报错。
        audio_payload = "".join(audio.split())
        audio_data = base64.b64decode(audio_payload, validate=True)
        if not audio_data:
            print("音频数据为空，未写入文件: ", savePath)
            return ""
        with open(savePath, 'wb') as audio_file:
            audio_file.write(audio_data)

        print("音频已保存: ", savePath)
        return savePath

    except Exception as e:
        print("音频转码出错: ", e)
        return ""
```

**根因**：`base64.b64decode()` 的默认参数是 `validate=False`，它会**静默丢弃**所有不在 Base64 字母表中的字符。传入 `"%%%%"` 时四个字符全被丢弃，剩下空串，于是 `b64decode` 返回 `b""` —— **不抛异常**。接下来的 `open(...,'wb')` 忠实地创建了一个 0 字节文件，函数返回非空路径，把"垃圾"包装成了"成功"。

**改动内容**：三件事
1. `"".join(audio.split())` 先剥离所有空白符 —— 这一步是为了**兼容性**，不是装饰。旧的 `validate=False` 会忽略换行，而火山等服务的 Base64 常常按 76 字符折行返回；如果直接加 `validate=True` 而不剥离空白，会把原本能保存的合法音频变成失败，制造一个新回归。
2. `validate=True` 严格解码，非法字符立即抛 `binascii.Error`，被既有 `except` 捕获后返回 `""`。
3. 空数据守卫 `if not audio_data: return ""` —— 兜住"解码成功但内容为空"的边角情形。

**实测对比**（在隔离目录中用 `git show HEAD:backend/Voice.py` 取出修复前版本，与工作区版本跑同一组输入）：

| 输入 | 版本 | 返回值 | 落盘字节数 |
|---|---|---|---|
| `"%%%%"`（TC-TTS-04 输入） | 修复前 | `'../frontend/src/assets/voice/Wendy/Wendy_3_Stream.mp3'` | **0 字节** |
| `"%%%%"` | 修复后 | `''` | **文件未创建** |

```
[修复前 (HEAD)]   传入: '%%%%'  返回值: '...Wendy_3_Stream.mp3'  异常: 无  落盘字节数: 0
[修复后 (工作区)] 传入: '%%%%'  返回值: ''                       异常: 无  落盘字节数: 文件未创建
                  控制台: 音频转码出错:  Only base64 data is allowed
```

**合法载荷回归验证**（确认没修坏正常路径）：

| 载荷形态 | 修复前 | 修复后 |
|---|---|---|
| 无换行（`b"fixed-mp3-bytes"` 的标准编码） | 成功，15 字节 | 成功，15 字节 |
| 含换行折行（每 8 字符换一行） | 成功，15 字节 | **成功，15 字节** |

两种形态在修复后都保持原有成功行为，`Voice_Generation_through_http` 的正常链路（TC-TTS-01）实测仍为 PASS。

---

### 3.2 修复二：非数字 index 让整条记录失配，异常提前发生且类型错误

**位置**：`backend/Integration.py`，函数 `Response_Collection` 的 Records 读取段

**修复前**

```python
            pattern = fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:(\d+)'
```

**修复后**

```python
            # index 捕获组放宽为 [^\n]*，使非数字索引（如 abc）也能被取出，
            # 从而在后续 int(index) 处显式失败，而不是让正则整条记录不匹配、
            # 导致 matches[0] 提前抛 IndexError 掩盖真实原因。
            pattern = fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:([^\n]*)'
```

**根因**：`index:(\d+)` 要求索引必须是纯数字。当 Records 里出现 `index:abc` 时，**整条记录都不匹配**，`re.findall` 返回空列表，紧接着第 121 行的 `imgurl, index = matches[0]` 抛出 `IndexError`。

这带来两个错误后果：
1. **异常类型与位置都不对**。`IndexError` 语义是"记录不存在"，会被排障者理解成"这个角色没写进 Records"，而真实原因是"索引字段是脏数据"。方向错了，排查成本成倍上升。文档 TC-EX-02 的预期写得很明确：应当在 LLM 与 TTS **都已被调用之后**，在 `int(index)` 处失败，用来验证"部分副作用后失败"的场景。
2. **异常提前发生，掩盖了真实执行边界**。副作用一个都没发生就崩了，无法暴露"外部服务已调用但状态未落盘"这个真正危险的中间态。

**改动内容**：捕获组从 `(\d+)` 放宽为 `([^\n]*)`，只负责把该行的值取出来，类型校验交给下游 `Integration.py:200` 的 `int(index)`。

**实测对比**：

| 场景 | 修复前 | 修复后 |
|---|---|---|
| `index:abc` | `matches=[]` → `matches[0]` 抛 `IndexError`，**LLM/TTS 均未被调用** | 抓到 `index='abc'` → `int('abc')` 抛 `ValueError`，**LLM/TTS 副作用已发生** |
| `index:3`（正常路径） | 抓到 `'3'`，流程正常 | 抓到 `'3'`，流程正常 |
| `index:9`（回绕路径） | 抓到 `'9'`，流程正常 | 抓到 `'9'`，流程正常 |

正常路径与边界路径的行为完全一致，只有"脏数据"这一支从"提前崩"变成"在正确位置崩"。

**副作用范围**：TC-EX-01（角色记录完全缺失）不受影响 —— 那种情况下正则本来就不该匹配，`IndexError` 仍是正确语义。现网 `frontend/src/assets/Records.txt` 中四个角色的 index 均为纯数字，无数据迁移成本。

---

## 4. 测试侧的必要同步改动

删除了 `backend/tests/test_service_and_state_cases.py` 中的 2 行装饰器：

```diff
-@pytest.mark.xfail(strict=True, reason="TC-TTS-04：当前实现会写入零字节音频")
 def test_tc_tts_04_invalid_base64_must_not_create_audio(monkeypatch, tmp_path):

-@pytest.mark.xfail(strict=True, reason="TC-EX-02：正则表达式先排除了非数字索引")
 def test_tc_ex_02_nonnumeric_index_fails_after_external_side_effects(monkeypatch, tmp_path):
```

**为什么必须删**：这两个标记都带 `strict=True`。`strict=True` 的语义是"**我断言它一定失败**" —— 一旦用例实际通过，pytest 会报 XPASS，并在 strict 模式下降级为 FAILED。也就是说，只改源码不删标记，运行结果会从"2 xfailed"变成"2 failed"，看起来像是修坏了。

**这两行删除不算"改测试来迁就代码"**：两条用例的断言本来就是按文档预期写的正确行为 ——
- TC-TTS-04 断言 `result == ""` 且 mp3 文件不存在；
- TC-EX-02 断言 `pytest.raises(ValueError)` 且 `calls == ["llm","tts"]`。

xfail 标记是当时用来"登记缺陷"的，缺陷修掉，标记自然要摘。删除后两条用例转为普通断言，测试强度反而更高（今后一旦回归，直接 FAILED 而不是被 xfail 吞掉）。

---

## 5. 未修复缺陷：为什么该修，不修会怎样

以下缺陷全部**保持原样未动**。本节说明每一项的技术理由与放任的后果，供后续逐条决策。

### 5.1 契约型缺陷 —— 现在"绿灯"，是因为断言的是错误行为（10 条）

这 10 条用例当前 PASS，但它们断言的是**当前实现的缺陷行为**。它们没被修，不是"没问题"，而是"问题被写进了断言"。

| 缺陷 | 位置 | 为什么该修 | 不修会怎样 |
|---|---|---|---|
| 缺 `type` / `payload` 靠 `KeyError` 冒泡报错 | `Connect.py:227` / `:233` | 用异常做流程控制，错误码无法区分"字段缺失"和"服务内部错误"，前端无法针对性提示 | 任何前端字段名写错，用户看到的是笼统的"内部服务器出错"，前后端联调时无法定位是谁的字段错了 |
| **PROCESS_ERROR 后缺 `continue`，导致双错误响应** | `Connect.py:237-241` | `except` 分支发完错误后没有 `continue`，继续用未绑定的 `resp` 构造响应 → `NameError` → 再触发外层 `SERVER_ERROR`，**一次请求回两条 error** | 前端 `pendingRequests` 按 `message_id` 匹配，第二条 error 没有对应请求，可能被当作新消息处理；且首条真实错误码 `PROCESS_ERROR` 会被后续 `SERVER_ERROR` 淹没，排障时看到的是误导性的"内部错误" |
| **error 消息不符合前端协议** | `Connect.py:290-311` | 前端 `isServerMessage()`（`frontend/src/utils/MessageType.ts:100-110`）要求 `type` + `message_id` + `payload` 三者齐备，当前 error 只有 `type/code/message/detail` | 前端会把**所有错误响应判为非法消息直接丢弃**。用户侧表现是"发消息后一直转圈直到 30 秒超时"，看不到任何错误提示 —— 这是最能消耗排查时间的故障形态 |
| **ACK 窗口内吞掉下一条业务请求** | `Connect.py:268-273` | 带内 ACK 与业务消息共用同一通道，`receive_json()` 不判类型，第二条 `client_query` 会被当作 ACK 消费 | 用户在前一条回复后 30 秒内连续发第二条消息，**第二条会被静默丢弃**，前端永远等不到响应直到超时。前端已实现 `message_id` 匹配（`ClientChat.ts:21/70`），后端这套带内 ACK 属冗余设计 |
| 角色记录缺失时抛 `IndexError` | `Integration.py:121` | 应在空列表时抛业务语义异常（如 `RecordsEntryNotFound`），错误信息带上 role 名 | 报错信息只有"list index out of range"，不含角色名，多角色场景下无法判断是哪个角色配置缺失 |
| Records 缺失时写入无恢复 | `Integration.py:85-95` | 读不到文件时已降级为静态模式，但写回阶段又会 `FileNotFoundError` 崩掉，**读的容错被写的脆弱抵消** | 首启场景（Records.txt 还没生成）下服务首次请求必然 500；即便 TTS、图片都成功，状态也无法落盘 |
| **同角色并发无锁，状态互相覆盖** | `Integration.py:117-203` | 整个"读 Records → 生成 → 写 Records"周期无任何同步，两个请求会读到同一个 index、写同一个 `Wendy_3_Stream.mp3`、后写者覆盖先写者的 Records 更新 | 两个用户同时跟同一角色对话时，**资源槽被串用、音频文件互相覆盖、Records 丢失更新**。用户听到的可能是别人的语音。这是多用户上线后的必然故障，不是概率问题 |
| TTS 失败但整体仍报 `status=success` | `Integration.py:158` | 前端无法从响应中区分"有音频"和"无音频" | 用户看到完整文字回复却没有语音，也不知道是网络问题还是设计如此，只能反复重试 |
| `updateLinks` 把已有 URL 清空 | `Integration.py:198/203` | 静态模式下 `static_images` 返回 `""`，随后无条件写回 Records，把 `Recent_Url:` 覆盖为空 | **这个缺陷已经真实发生**：现网 `frontend/src/assets/Records.txt` 中 Wendy / Testificate / GirlProgrammer 三者的 `Recent_Url:` 均为空。后果是实时图生图找不到参考图，永远退化成文生图，角色形象在每次实时渲染后都会漂移 |
| `if f"{roleName}:\n" in lines[i]` 用 `in` 而非 `==` | `Integration.py:91` | 子串匹配会误命中 | 若同时存在 `Wendy` 和 `Wendy2` 两个角色，更新 `Wendy` 时会连带改写 `Wendy2` 的记录 |

**为什么不现在一起修**：这些修改会**同时改变已通过用例的断言**（改完必须重写 10 条用例的期望值），属于契约变更而非缺陷修补，风险面和确认成本都远高于本次的两处单行修复。应当逐条确认"改实现还是改用例"之后再动。

### 5.2 真实 Bug —— 没有任何测试覆盖，测试全绿也发现不了

| 缺陷 | 位置 | 为什么该修 | 不修会怎样 |
|---|---|---|---|
| **`delta.content != ""` 对 `None` 为真** | `Text.py:54` | OpenAI 流式响应的**最后一个 chunk** 的 `delta.content` 是 `None`，而 `None != ""` 恒为 `True`，于是执行 `answer_content += None` → `TypeError` | **真实调用必然崩溃**。当前所有测试的 mock 都固定返回字符串，永远测不出这条。上线后每一次对话都会在流结束时抛异常，被 `Connect.py` 捕获后回 `PROCESS_ERROR` —— 而用户已经看到了部分文字，表现为"回复到一半断掉"。修法是把 `!= ""` 改成真值判断 |
| 正则里 `\0` 是 NUL 字符 | `Image.py:83` | `(?=\0|$)` 中的 `\0` 是 C 语言习惯的笔误，Python 正则是 `\x00`，永远不会匹配文本，等价于只有 `$` | 实测：对 `Subject Description: aaa\nAppearance Details: bbb\nccc`，appearance 捕获结果是 `'bbb\nccc'` —— **吃掉换行之后的全部内容**。角色描述文件里若在 appearance 之后追加任何字段，都会被并入外观描述，污染图像生成的正面提示词 |
| 裸索引 `[0]` | `Image.py:85-88` | `get_role_image_prompt` 对 `re.findall` 结果直接取 `[0]` | 角色描述文件为空或格式不符时抛 `IndexError`，且异常信息不指向具体角色 |
| 图片下载无 timeout / 无重试 / 失败被吞 | `Image.py:27-45` | `requests.get(url, stream=True)` 无超时；异常只 `print` 后返回 `False`，而调用方 `Image.py:133/193/209` 不检查返回值 | 图片服务响应慢时线程会无限期挂起；下载失败时静默返回，用户拿到的是**文字和语音都正常、唯独图片永远不更新**的"半瘫"状态，且日志里没有任何可追溯的错误 |
| `reqid` 全局复用 | `Voice.py:22` / `:237` | 模块级 `uuid.uuid4()` 在导入时只求值一次，之后所有 TTS 请求共用同一个 `reqid` | 火山服务端可能按 `reqid` 做去重/缓存，导致不同文本返回同一段音频。这类问题表现为"偶发音画不同步"，极难定位 |
| 裸 `except:` | `Integration.py:151` | 会吞掉 `KeyboardInterrupt` / `SystemExit` | 情绪解析段执行期间无法用 Ctrl-C 中断进程，只能强杀 |
| 默认 index 硬编码 `"8"` | `Connect.py:175` | `ServerResponse` 的初值 `index = "8"` 无业务含义 | 任何异常路径返回的 index 都是 8，前端会去索引不存在的 `_8_Stream.mp3` |

### 5.3 架构级缺陷 —— 测试 mock 全部掩盖

| 缺陷 | 位置 | 为什么该修 | 不修会怎样 |
|---|---|---|---|
| **同步阻塞事件循环** | `Connect.py:238` 直接调用同步 `process_query` | `websocket_chat` 是 `async`，但内部串行执行 LLM 流式请求 + TTS HTTP(30s) + 火山图片生成（SDK 同步阻塞）。**单个请求会占满整个 uvicorn 事件循环** | 一个用户发起请求时，**其余所有 WebSocket 连接全部无响应**，包括心跳和错误回复。并发用户数一旦超过 1 就会暴露；测试全用 mock 毫秒级返回，完全测不出。修法是 `asyncio.to_thread` 或 `run_in_threadpool` |
| **7 处相对路径依赖 cwd** | `Voice.py:113/193`、`Image.py:48/72/108/159/220`、`Integration.py:86/89/117`、`Text.py:14` 均用 `../frontend/src/assets/...` | 只有启动时 cwd 恰好是 `backend/` 才正确 | 换一种启动方式（如从仓库根执行 `uvicorn backend.Connect:app`、或在 IDE 里以项目根为工作目录运行）就会把资源和状态写到错误目录，表现为"代码明明没错但就是找不到角色文件"。**注意**：修复需同步调整测试里的 `monkeypatch.chdir(tmp/"backend")` 假设，否则 34 条用例会大面积转红，所以不适合与本次单行修复混在一起做 |
| Records.txt 用文本文件承载并发状态 | `Integration.py:85-95` | 无锁、非原子、用行号偏移改写 | 见 5.1 中"同角色并发"一条；此外写入过程中的任何中断都会让文件处于半写状态 |

### 5.4 工程卫生与安全

| 缺陷 | 位置 | 为什么该修 | 不修会怎样 |
|---|---|---|---|
| **6 处 API 密钥硬编码入库** | `Voice.py:17-18`（appid/token）、`Voice.py:116/213`（token 明文重复）、`Text.py:38`（OpenAI key）、`Image.py:9-10`、`TestSubject2.py:8-9`、`image_emotions.py:4-5`（火山 AK/SK） | 仓库已含 LICENSE 与 README，处于可公开状态；`SECRET` 还是 base64 明文，可直接解码 | 密钥泄露后会被他人盗刷，产生**真实账单**（LLM/TTS/图片生成三项都是按量计费）。**只删代码不够，已泄漏的 key 必须作废轮换** —— git 历史里仍然留着 |
| `pytest.ini` 缺 `testpaths` | `backend/pytest.ini` | 仓库根存在 `backend/test_websocket.py`，它会连接真实 `ws://localhost:8000` 并调用真实 LLM/TTS/火山，无 mock 无跳过标记 | 当前靠 `run_module1_tests.sh` 显式传 `tests` 参数兜住。**任何人在 IDE 里直接点一次 pytest，或在 CI 里跑一次裸 `pytest`，就会发起真实计费调用**；若后端服务未启动还会挂起等待连接 |
| 无关污染文件且含语法错误 | `backend/TestSubject.py` | 是火山 ECS SDK 示例（创建云主机），与项目无关；`from __future__ import print_function` 位于第 5 行 | 已验证为 `SyntaxError`。任何全量 `pytest` 收集、`compileall`、或 IDE 全项目索引都会因此报错，干扰对其他真实问题的判断 |
| 重复且不一致的音色定义 | `backend/TestSubject2.py:38` | `StandardBoyfriend.code` 用 `zh_male_yangguangqingnian_...`，与 `Integration.py:48` 的 `zh_male_yourougongzi_...` 冲突 | 后来者无法判断哪份是现役配置，改错一处就会出现"男声角色用了错误音色"且难以复现 |
| `Voice.request_confirmation` 与 `Integration.request_confirmation` 同名不同语义 | `Voice.py:36-61` / `Integration.py:38-82` | 前者收整数音色编号 0-3，后者收 `"GirlFriend"` 类别字符串 | 排查语音问题时极易调错函数、得出错误结论 |
| 已入库的构建产物 | `backend/__pycache__/*.pyc` 7 个、`backend/.idea/` 9 个文件 | 二进制产物与 IDE 配置不应入库 | 每次运行测试都可能产生 diff 噪声，掩盖真实改动。（注：`PYTHONDONTWRITEBYTECODE=1` 已在脚本中生效，本次修复经核对**未改写任何 pyc**） |
| 依赖清单是 `pip freeze` 快照 | `backend/requirements.txt` | 混入 Flask、SQLAlchemy、redis、mysqlclient、websocat 等无关项；真正的运行最小集接近 `requirements-test.txt` 那 7 行 | 环境重建缓慢且易冲突；更关键的是 `tests/conftest.py:17-39` 为 `openai`/`volcengine` 注入 stub，**意味着生产 SDK 从未被任何测试覆盖** |
| 跨端字段名不一致 | `frontend/src/stores/ClientChat.ts:86-88`、`UseChatClient.ts:81` 用 `imageMode_config`；`MessageType.ts:40`、`ChatView.vue:507`、`Connect.py:138` 用 `imageModel_config` | 需先确认前端实际走哪条链路（静态检查发现，未实跑前端） | 若实际走 Store 链路，发往后台的 payload 会缺 `imageModel_config`，被 Pydantic 拦成 `VALIDATION_ERROR`；叠加 5.1 中"error 消息不符合前端协议"一条，用户侧表现为**永久转圈无提示**，两端各自测都正常，只有联调才暴露 |

---

## 6. 本次变更清单

| 文件 | 变更 | 性质 |
|---|---|---|
| `backend/Voice.py` | `save_audio_from_base64`：严格 Base64 解码 + 剥离空白 + 空数据守卫（净 +7 行，含 3 行注释） | 生产代码修复 |
| `backend/Integration.py` | `Response_Collection`：index 捕获组 `(\d+)` → `([^\n]*)`（净 +3 行注释，核心改动 1 行） | 生产代码修复 |
| `backend/tests/test_service_and_state_cases.py` | 删除 2 行 `@pytest.mark.xfail` 装饰器 | 测试标记同步（缺陷已消除） |
| `scripts/run_module1_tests.sh` | 上一轮已加固，本次未再改动 | 前置工作 |
| `docs/module1/LLMGal_backend_程序修正指南.md` | 上一轮产出，本次未改动 | 参考文档 |
| `docs/module1/LLMGal_backend_bug修复对比报告.md` | 本报告 | 交付物 |

**未纳入版本控制的操作**：`git status` 显示仅上述 4 个 tracked 文件被修改 + 3 个未跟踪文档，**无任何 commit / push**。所有对比实验都在 `%TEMP%\llmgal_probe\` 隔离目录内完成，未污染仓库。

---

## 7. 回归验证方式

```bash
"/c/Program Files/Git/bin/bash.exe" "F:/LLMGal/scripts/run_module1_tests.sh"
```

判定标准：
- 输出末行 `34 passed`（不再有 `xfailed`）
- `artifacts/test-results/module1-junit.xml`：`tests=34 errors=0 failures=0 skipped=0`
- `git diff --name-only -- backend/__pycache__` 无输出（确认 pyc 未被改写）

调试技巧：改完先跑 `pytest tests -q -rxX`。`-rxX` 会打印 xfail/xpass 的原因 —— **重点看 XPASS**，本仓库的 xfail 均为 `strict=True`，用例一旦通过反而判失败，这是"改完源码怎么还是红的"最常见的原因。
